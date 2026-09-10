"""The migration census: what it counts, and what it refuses to disclose.

These run against the in-memory SQLite database, which is the point — the
census is engine-agnostic by construction, so if it needed Postgres to work it
would be useless for comparing Postgres against something else.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import ContentPlatform, ContentStatus, MediaSource
from app.db.inventory import collect, compare
from app.db.models import (
    ContentItem,
    ContentItemMedia,
    Course,
    CourseOffering,
    MediaAsset,
    User,
)


async def _populate(session: AsyncSession) -> dict[str, uuid.UUID]:
    user = User(
        email="admin@wrcc.local",
        password_hash="not-a-real-hash",
        display_name="Admin",
    )
    course = Course(course_code="BSB123", title="First Aid")
    session.add_all([user, course])
    await session.flush()

    session.add(
        CourseOffering(course_id=course.id, offering_code="BSB123-1", status="active")
    )
    item = ContentItem(
        platform=ContentPlatform.facebook,
        variant_style="informative",
        generated_body="Enrol now.",
        status=ContentStatus.draft,
    )
    asset = MediaAsset(
        source=MediaSource.uploaded,
        mime_type="image/jpeg",
        width=100,
        height=100,
        byte_size=5,
        checksum="abc123",
        data=b"12345",
    )
    session.add_all([item, asset])
    await session.flush()

    session.add(
        ContentItemMedia(content_item_id=item.id, media_asset_id=asset.id, position=0)
    )
    await session.commit()
    return {"user": user.id, "item": item.id, "asset": asset.id}


async def test_counts_every_table_including_the_empty_ones(
    db_session: AsyncSession,
) -> None:
    """An empty table must report 0, not go missing.

    A table that vanishes from the report is a table whose loss the comparison
    cannot detect.
    """
    await _populate(db_session)

    report = await collect(db_session)

    assert report["tables"]["users"] == 1
    assert report["tables"]["courses"] == 1
    assert report["tables"]["course_offerings"] == 1
    assert report["tables"]["content_items"] == 1
    assert report["tables"]["media_assets"] == 1
    assert report["tables"]["content_item_media"] == 1
    # Never populated above — and still present, reporting zero.
    assert report["tables"]["content_publications"] == 0
    assert report["tables"]["social_accounts"] == 0
    assert report["tables"]["audit_logs"] == 0


async def test_breaks_down_the_columns_a_migration_can_scramble(
    db_session: AsyncSession,
) -> None:
    """Enums are the ones at risk: Postgres stores a type, MySQL stores text."""
    await _populate(db_session)

    report = await collect(db_session)

    assert report["breakdowns"]["content_items_by_status"] == {"draft": 1}
    assert report["breakdowns"]["content_items_by_platform"] == {"facebook": 1}
    assert report["breakdowns"]["media_assets_by_source"] == {"uploaded": 1}


async def test_compares_recorded_byte_size_against_stored_length(
    db_session: AsyncSession,
) -> None:
    """The truncated-BLOB detector."""
    await _populate(db_session)

    report = await collect(db_session)

    assert report["integrity"]["media_bytes_recorded"] == 5
    assert report["integrity"]["media_bytes_stored"] == 5
    assert report["integrity"]["media_bytes_match"] is True


async def test_counts_orphans_left_by_a_dropped_foreign_key(
    db_session: AsyncSession,
) -> None:
    """A restore that lost a constraint leaves rows pointing nowhere.

    Nothing else in the report moves when this happens — the counts still
    match — so this is the only signal.
    """
    await _populate(db_session)
    session_free_id = uuid.uuid4()
    db_session.add(
        CourseOffering(
            course_id=session_free_id, offering_code="ORPHAN-1", status="active"
        )
    )
    await db_session.commit()

    report = await collect(db_session)

    assert report["orphans"]["course_offerings.course_id"] == 1


async def test_the_report_names_no_user_and_no_secret(
    db_session: AsyncSession,
) -> None:
    """It gets pasted into tickets, so it carries hashes, not identities."""
    await _populate(db_session)

    report = await collect(db_session)
    serialized = str(report)

    for disclosed in ("admin@wrcc.local", "not-a-real-hash", "abc123", "Enrol now."):
        assert disclosed not in serialized


async def test_fingerprints_survive_a_change_of_row_order(
    db_session: AsyncSession,
) -> None:
    """A dump and restore does not preserve insertion order.

    A fingerprint sensitive to it would flag every single migration as broken,
    which is the same as having no check at all.
    """
    ids = [str(uuid.uuid4()) for _ in range(5)]

    from app.db.inventory import _fingerprint

    assert _fingerprint(ids) == _fingerprint(list(reversed(ids)))
    assert _fingerprint(ids) != _fingerprint(ids[:-1])


# ── compare ──


def _report(**overrides) -> dict:
    base = {
        "generated_at": "2026-09-08T00:00:00+00:00",
        "tables": {"users": 2, "content_items": 7},
        "breakdowns": {"content_items_by_status": {"draft": 4, "published": 3}},
        "time_bounds": {"users": {"earliest": "2026-01-01T00:00:00+00:00", "latest": None}},
        "orphans": {"content_item_media.content_item_id": 0},
        "fingerprints": {"user_ids": "deadbeefdeadbeef"},
        "integrity": {
            "media_bytes_recorded": 10,
            "media_bytes_stored": 10,
            "media_bytes_match": True,
        },
    }
    base.update(overrides)
    return base


def test_identical_reports_compare_clean() -> None:
    assert compare(_report(), _report()) == []


def test_a_lost_row_is_reported() -> None:
    problems = compare(_report(), _report(tables={"users": 2, "content_items": 6}))

    assert len(problems) == 1
    assert "content_items" in problems[0]


def test_a_changed_fingerprint_is_reported_even_when_the_count_matches() -> None:
    """Same number of users, different users. Counting alone would miss it."""
    problems = compare(_report(), _report(fingerprints={"user_ids": "0000000000000000"}))

    assert any("not the same set" in problem for problem in problems)


def test_truncated_media_is_reported() -> None:
    after = _report(
        integrity={
            "media_bytes_recorded": 10,
            "media_bytes_stored": 4,
            "media_bytes_match": False,
        }
    )

    problems = compare(_report(), after)

    assert any("truncated" in problem for problem in problems)


def test_a_shifted_timestamp_range_is_reported() -> None:
    """The tz-naive failure mode: same rows, moved in time."""
    after = _report(
        time_bounds={"users": {"earliest": "2025-12-31T13:00:00", "latest": None}}
    )

    problems = compare(_report(), after)

    assert any("timezone" in problem for problem in problems)


def test_orphans_appearing_only_after_the_move_are_reported() -> None:
    after = _report(orphans={"content_item_media.content_item_id": 3})

    problems = compare(_report(), after)

    assert any("orphaned" in problem for problem in problems)


@pytest.mark.parametrize(
    "overrides",
    [
        {"tables": {"users": 3, "content_items": 7}},
        {"breakdowns": {"content_items_by_status": {"draft": 7}}},
        {"orphans": {"content_item_media.content_item_id": 1}},
    ],
)
def test_every_difference_class_is_caught(overrides: dict) -> None:
    assert compare(_report(), _report(**overrides)) != []


def test_generated_at_is_not_a_difference() -> None:
    """The two censuses are taken minutes apart by definition."""
    later = _report(generated_at=dt.datetime.now(dt.UTC).isoformat())

    assert compare(_report(), later) == []
