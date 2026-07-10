"""Integration: sync → pending changeset → approve/reject → live catalog."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import AuditLog
from app.scraper.discovery import parse_category_page
from app.scraper.normalize import build_course_groups
from app.scraper.parser import parse_course_detail
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
