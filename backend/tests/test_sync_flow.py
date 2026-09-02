"""Integration: sync → pending changeset → approve/reject → live catalog."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import AuditLog, Course, CourseOffering
from app.scraper.discovery import parse_category_page
from app.scraper.normalize import build_course_groups
from app.scraper.parser import parse_course_detail
from app.scraper.repository import CatalogRepository
from app.scraper.service import SyncService
from app.scraper.types import ScrapedCourseGroup
from tests.conftest import FIXTURES, make_settings

WRCC = FIXTURES / "wrcc"


def _fixture_groups() -> list[ScrapedCourseGroup]:
    """Groups built from the captured fixtures via the real discovery/parser."""
    entries = []
    for category_file, category, detail_file, course_id in (
        ("category_first_aid.html", "First Aid", "detail_106860.html", "106860"),
        (
            "category_plant_and_equipment.html",
            "Plant and Equipment",
            "detail_74271.html",
            "74271",
        ),
    ):
        cards = parse_category_page(
            (WRCC / category_file).read_text(encoding="utf-8"), category=category
        )
        detail_html = (WRCC / detail_file).read_text(encoding="utf-8")
        for card in cards:
            if course_id in (card.detail_url or ""):
                description, offerings = parse_course_detail(
                    detail_html,
                    detail_url=card.detail_url,
                    base_url="https://wrcc.nsw.edu.au",
                )
                entries.append((card, description, offerings))
            else:
                entries.append((card, card.description, []))
    return build_course_groups(entries)


@pytest.fixture
def sync_service(db_sessionmaker, monkeypatch: pytest.MonkeyPatch) -> SyncService:
    async def crawler(_settings: Settings) -> list[ScrapedCourseGroup]:
        return _fixture_groups()

    service = SyncService(db_sessionmaker, make_settings(), crawler=crawler)
    monkeypatch.setattr("app.api.courses.get_sync_service", lambda: service)
    return service


async def _run_sync(auth_client: AsyncClient, sync_service: SyncService) -> dict:
    response = await auth_client.post("/api/courses/sync")
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "running"
    await sync_service.wait_for_pending()
    detail = await auth_client.get(f"/api/courses/sync/{run['id']}")
    assert detail.status_code == 200
    return detail.json()


async def test_sync_requires_auth(client: AsyncClient) -> None:
    assert (await client.post("/api/courses/sync")).status_code == 401
    assert (await client.get("/api/courses")).status_code == 401


async def test_full_sync_approve_flow(
    auth_client: AsyncClient, sync_service: SyncService, db_sessionmaker
) -> None:
    run = await _run_sync(auth_client, sync_service)
    assert run["status"] == "pending"
    assert run["courses_found"] > 0
    assert run["offerings_found"] > 20
    assert run["changeset"]["summary"]["courses_added"] == run["courses_found"]

    # Approve applies the changeset to the live catalog.
    approve = await auth_client.post(f"/api/courses/sync/{run['id']}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    courses = (await auth_client.get("/api/courses")).json()
    codes = {course["course_code"] for course in courses}
    assert {"HLTAID011", "TLILIC0003"} <= codes

    first_aid = next(c for c in courses if c["course_code"] == "HLTAID011")
    assert first_aid["is_accredited"] is True
    detail = (await auth_client.get(f"/api/courses/{first_aid['id']}")).json()
    assert len(detail["offerings"]) >= 10
    assert detail["offerings"][0]["price"] == 185.0

    # Search filter finds the forklift course.
    filtered = (await auth_client.get("/api/courses", params={"search": "forklift"})).json()
    assert {c["course_code"] for c in filtered} == {"TLILIC0003"}

    # Approval is audited.
    async with db_sessionmaker() as session:
        actions = {
            log.action
            for log in (await session.execute(select(AuditLog))).scalars()
        }
    assert "catalog_sync_started" in actions
    assert "catalog_sync_approved" in actions

    # Idempotency: an identical re-scrape stages an empty changeset.
    rerun = await _run_sync(auth_client, sync_service)
    assert rerun["status"] == "pending"
    assert all(count == 0 for count in rerun["changeset"]["summary"].values())


async def test_reject_leaves_catalog_untouched(
    auth_client: AsyncClient, sync_service: SyncService
) -> None:
    run = await _run_sync(auth_client, sync_service)

    reject = await auth_client.post(
        f"/api/courses/sync/{run['id']}/reject", json={"reason": "bad data"}
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "rejected"

    assert (await auth_client.get("/api/courses")).json() == []

    # A reviewed run cannot be reviewed again.
    again = await auth_client.post(f"/api/courses/sync/{run['id']}/approve")
    assert again.status_code == 409


async def test_concurrent_sync_is_rejected(
    auth_client: AsyncClient, sync_service: SyncService
) -> None:
    first = await auth_client.post("/api/courses/sync")
    assert first.status_code == 202
    await sync_service.wait_for_pending()

    # First run is now pending review — a second sync must not start.
    second = await auth_client.post("/api/courses/sync")
    assert second.status_code == 409


async def test_zero_offering_crawl_fails_run(
    auth_client: AsyncClient, db_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def empty_crawler(_settings: Settings) -> list[ScrapedCourseGroup]:
        return []

    service = SyncService(db_sessionmaker, make_settings(), crawler=empty_crawler)
    monkeypatch.setattr("app.api.courses.get_sync_service", lambda: service)

    response = await auth_client.post("/api/courses/sync")
    assert response.status_code == 202
    await service.wait_for_pending()

    run = (await auth_client.get(f"/api/courses/sync/{response.json()['id']}")).json()
    assert run["status"] == "failed"
    assert "zero offerings" in run["error"]


async def test_legacy_removed_codes_still_apply(db_sessionmaker) -> None:
    """A run staged before removals carried context holds bare code strings.

    Such a run can still be sitting in review, so approving it has to keep
    working rather than silently skipping the deactivations.
    """
    async with db_sessionmaker() as session:
        repository = CatalogRepository(session)
        await repository.apply_changeset(
            {
                "courses_added": [
                    {
                        "course_code": "OLD101",
                        "title": "Legacy course",
                        "offerings": [{"offering_code": "9001", "status": "active"}],
                    }
                ]
            }
        )
        await session.commit()

        await repository.apply_changeset(
            {"courses_removed": ["OLD101"], "offerings_removed": ["9001"]}
        )
        await session.commit()

        course = (
            await session.execute(select(Course).where(Course.course_code == "OLD101"))
        ).scalar_one()
        offering = (
            await session.execute(
                select(CourseOffering).where(CourseOffering.offering_code == "9001")
            )
        ).scalar_one()

    assert course.is_active is False
    assert offering.is_active is False


async def test_approve_skips_the_entries_the_reviewer_unticked(
    auth_client: AsyncClient, sync_service: SyncService, db_sessionmaker
) -> None:
    """Partial approval writes the kept rows and leaves the skipped ones alone."""
    run = await _run_sync(auth_client, sync_service)
    added = run["changeset"]["courses_added"]
    kept, skipped = added[0]["course_code"], added[1]["course_code"]

    response = await auth_client.post(
        f"/api/courses/sync/{run['id']}/approve",
        json={"skip": {"courses_added": [skipped]}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    codes = {
        course["course_code"]
        for course in (await auth_client.get("/api/courses")).json()
    }
    assert kept in codes
    assert skipped not in codes

    # The run still records everything the crawl saw, not just what was applied.
    detail = (await auth_client.get(f"/api/courses/sync/{run['id']}")).json()
    staged = {c["course_code"] for c in detail["changeset"]["courses_added"]}
    assert {kept, skipped} <= staged


async def test_skipped_entries_are_staged_again_by_the_next_sync(
    auth_client: AsyncClient, sync_service: SyncService
) -> None:
    """Unticking is 'not now': the upstream difference is still there."""
    run = await _run_sync(auth_client, sync_service)
    skipped = run["changeset"]["courses_added"][0]["course_code"]

    await auth_client.post(
        f"/api/courses/sync/{run['id']}/approve",
        json={"skip": {"courses_added": [skipped]}},
    )

    rerun = await _run_sync(auth_client, sync_service)
    restaged = {c["course_code"] for c in rerun["changeset"]["courses_added"]}
    assert restaged == {skipped}


async def test_approve_records_what_was_applied_and_what_was_passed_over(
    auth_client: AsyncClient, sync_service: SyncService, db_sessionmaker
) -> None:
    run = await _run_sync(auth_client, sync_service)
    skipped = run["changeset"]["courses_added"][0]["course_code"]
    staged_count = run["changeset"]["summary"]["courses_added"]

    await auth_client.post(
        f"/api/courses/sync/{run['id']}/approve",
        json={"skip": {"courses_added": [skipped]}},
    )

    async with db_sessionmaker() as session:
        entry = next(
            log
            for log in (await session.execute(select(AuditLog))).scalars()
            if log.action == "catalog_sync_approved"
        )
        diff = entry.payload_diff

    assert diff["skipped"] == {"courses_added": [skipped]}
    assert diff["skipped_count"] == 1
    assert diff["staged"]["courses_added"] == staged_count
    assert diff["applied"]["courses_added"] == staged_count - 1


async def test_approve_without_a_body_still_applies_everything(
    auth_client: AsyncClient, sync_service: SyncService
) -> None:
    """The old whole-changeset approve is still exactly what an empty call does."""
    run = await _run_sync(auth_client, sync_service)
    staged = {c["course_code"] for c in run["changeset"]["courses_added"]}

    await auth_client.post(f"/api/courses/sync/{run['id']}/approve")

    codes = {
        course["course_code"]
        for course in (await auth_client.get("/api/courses")).json()
    }
    assert staged <= codes


async def test_unknown_skip_codes_are_ignored_rather_than_failing(
    auth_client: AsyncClient, sync_service: SyncService
) -> None:
    run = await _run_sync(auth_client, sync_service)
    staged = {c["course_code"] for c in run["changeset"]["courses_added"]}

    response = await auth_client.post(
        f"/api/courses/sync/{run['id']}/approve",
        json={"skip": {"courses_added": ["NOT-IN-THIS-RUN"]}},
    )
    assert response.status_code == 200

    codes = {
        course["course_code"]
        for course in (await auth_client.get("/api/courses")).json()
    }
    assert staged <= codes
