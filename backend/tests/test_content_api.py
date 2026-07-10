"""Integration: generation, history filters, and the full HITL workflow."""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import AsyncClient

import app.content.service as content_service
from app.db.models import Course, CourseOffering


async def _seed_course(db_sessionmaker) -> str:
    async with db_sessionmaker() as session:
        course = Course(
            course_code="HLTAID011",
            title="HLTAID011 Provide First Aid",
            category="First Aid",
            description="Robust, industry supported first aid standards.",
            is_accredited=True,
            source_url="https://wrcc.nsw.edu.au/course-details/?course_id=106860",
            is_active=True,
        )
        session.add(course)
        await session.flush()
        session.add(
            CourseOffering(
                course_id=course.id,
                offering_code="2392073",
                price=185.0,
                status="active",
                places_available=10,
                location="WRCC Deniliquin",
                start_date=dt.date(2026, 7, 24),
                finish_date=dt.date(2026, 7, 24),
                time_text="09:00 am – 03:30 pm",
                enrollment_url="https://wrcc.nsw.edu.au/course-enrol?instance_id=2392073",
                is_active=True,
            )
        )
        await session.commit()
        return str(course.id)


async def test_generate_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/content/generate",
        json={"topic": "x", "platforms": ["facebook"]},
    )
    assert response.status_code == 401


async def test_generate_requires_topic_or_course(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/content/generate", json={"platforms": ["facebook"]}
    )
    assert response.status_code == 422


async def test_generate_three_variants_per_platform(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/content/generate",
        json={
            "topic": "Spring first aid enrolments",
            "notes": "Mention Griffith campus",
            "platforms": ["facebook", "linkedin"],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert len(payload["items"]) == 6
    by_platform: dict[str, list[dict]] = {}
    for item in payload["items"]:
        by_platform.setdefault(item["platform"], []).append(item)
    assert set(by_platform) == {"facebook", "linkedin"}
    for platform_items in by_platform.values():
        assert {i["variant_style"] for i in platform_items} == {
            "direct",
            "story_led",
            "question_led",
        }
        assert all(i["status"] == "draft" for i in platform_items)
        assert all(
            i["generation_group"] == payload["generation_group"]
            for i in platform_items
        )
    # Mock metadata is recorded for traceability.
    assert payload["items"][0]["ai_metadata"]["mock"] is True


async def test_generate_grounded_in_real_course(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    course_id = await _seed_course(db_sessionmaker)

    response = await auth_client.post(
        "/api/content/generate",
        json={"course_id": course_id, "platforms": ["instagram"]},
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 3
    # Real catalog facts flow into the generated copy and the stored context.
    assert any("HLTAID011" in item["body"] for item in items)
    context_course = items[0]["ai_metadata"]["context"]["course"]
    assert context_course["course_code"] == "HLTAID011"
    assert context_course["upcoming_offerings"][0]["location"] == "WRCC Deniliquin"
    assert context_course["upcoming_offerings"][0]["price"] == 185.0


async def test_generate_unknown_course_404(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/content/generate",
        json={
            "course_id": "00000000-0000-0000-0000-000000000001",
            "platforms": ["facebook"],
        },
    )
    assert response.status_code == 404


async def test_reference_url_failure_never_blocks(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken_fetch(url: str, settings) -> tuple[str | None, str | None]:
        return None, f"reference URL could not be fetched: {url}"

    monkeypatch.setattr(content_service, "fetch_reference_excerpt", broken_fetch)

    response = await auth_client.post(
        "/api/content/generate",
        json={
            "topic": "Forklift licences",
            "reference_url": "https://unreachable.example/page",
            "platforms": ["facebook"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 3
    assert any("could not be fetched" in warning for warning in payload["warnings"])


async def test_history_filters(auth_client: AsyncClient) -> None:
    await auth_client.post(
        "/api/content/generate",
        json={"topic": "Yoga term 3", "platforms": ["facebook", "instagram"]},
    )

    everything = (await auth_client.get("/api/content")).json()
    assert len(everything) == 6

    facebook_only = (
        await auth_client.get("/api/content", params={"platform": "facebook"})
    ).json()
    assert len(facebook_only) == 3
    assert all(item["platform"] == "facebook" for item in facebook_only)

    drafts = (
        await auth_client.get("/api/content", params={"status_filter": "draft"})
    ).json()
    assert len(drafts) == 6
    assert (
        await auth_client.get("/api/content", params={"status_filter": "approved"})
    ).json() == []


async def test_full_workflow_submit_approve_reject_edit(
    auth_client: AsyncClient,
) -> None:
    generated = (
        await auth_client.post(
            "/api/content/generate",
            json={"topic": "Barista basics", "platforms": ["facebook"]},
        )
    ).json()
    first, second, third = (item["id"] for item in generated["items"])

    # draft → pending → approved (reviewer stamped).
    assert (await auth_client.post(f"/api/content/{first}/submit")).json()[
        "status"
    ] == "pending_approval"
    approved = (await auth_client.post(f"/api/content/{first}/approve")).json()
    assert approved["status"] == "approved"
    assert approved["reviewed_at"] is not None

    # Approving a draft directly violates the state machine → 409.
    assert (await auth_client.post(f"/api/content/{second}/approve")).status_code == 409

    # draft → pending → rejected(reason) → edit reopens as draft.
    await auth_client.post(f"/api/content/{second}/submit")
    rejected = (
        await auth_client.post(
            f"/api/content/{second}/reject", json={"reason": "off brand"}
        )
    ).json()
    assert rejected["status"] == "rejected"
    edited = (
        await auth_client.put(
            f"/api/content/{second}", json={"body": "A fresh hand-written body."}
        )
    ).json()
    assert edited["status"] == "draft"
    assert edited["edited_body"] == "A fresh hand-written body."
    assert edited["body"] == "A fresh hand-written body."

    # archive → restore.
    assert (await auth_client.post(f"/api/content/{third}/archive")).json()[
        "status"
    ] == "archived"
    assert (await auth_client.post(f"/api/content/{third}/restore")).json()[
        "status"
    ] == "draft"


async def test_duplicate_and_regenerate(auth_client: AsyncClient) -> None:
    generated = (
        await auth_client.post(
            "/api/content/generate",
            json={"topic": "White card training", "platforms": ["linkedin"]},
        )
    ).json()
    source = generated["items"][0]

    duplicate = (
        await auth_client.post(f"/api/content/{source['id']}/duplicate")
    ).json()
    assert duplicate["id"] != source["id"]
    assert duplicate["status"] == "draft"
    assert duplicate["body"] == source["body"]
    assert duplicate["ai_metadata"]["duplicated_from"] == source["id"]

    regenerated = (
        await auth_client.post(
            f"/api/content/{source['id']}/regenerate",
            json={"instruction": "make it shorter"},
        )
    ).json()
    assert regenerated["id"] != source["id"]
    assert regenerated["status"] == "draft"
    assert regenerated["ai_metadata"]["regenerated_from"] == source["id"]
    assert regenerated["ai_metadata"]["instruction"] == "make it shorter"
    assert regenerated["generation_group"] == source["generation_group"]

    # The regenerated draft joins the same group in history.
    group_items = (
        await auth_client.get(
            "/api/content", params={"generation_group": source["generation_group"]}
        )
    ).json()
    assert len(group_items) == 5  # 3 originals + duplicate + regeneration
