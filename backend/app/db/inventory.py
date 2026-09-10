"""Read-only census of a database, for comparing one against another.

The point of this module is a migration: you take a fingerprint of the source,
you take the same fingerprint of the target, and the two must be identical. It
therefore never writes, and it deliberately reports only things that must
survive a move between engines — counts, relationships, and boundary values —
never anything engine-specific like an index name or a column type, which are
*expected* to differ and would drown the real signal.

Two rules shaped what is in here:

* **No secrets.** The report is written to a file and pasted into tickets, so
  it carries no connection string, no email address, no filename, no token.
  Where identity matters (did *this* user survive?) it carries a hash.
* **Orphans are counted, not assumed.** A dump/restore across engines can drop
  a foreign key silently; a row whose parent is gone still reads fine until
  someone opens it. Counting them is the only way to see it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    ContentItem,
    ContentItemMedia,
    ContentPublication,
    ContentPublicationMedia,
    Course,
    CourseOffering,
    MediaAsset,
    ScraperRun,
    SocialAccount,
    User,
)

# Ordered parent-first, so a reader sees the tables a broken foreign key would
# point at before the tables that point at them.
TABLES = (
    User,
    Course,
    CourseOffering,
    ScraperRun,
    ContentItem,
    MediaAsset,
    ContentItemMedia,
    SocialAccount,
    ContentPublication,
    ContentPublicationMedia,
    AuditLog,
)

# (child, child FK attribute, parent) triples whose orphans are worth counting.
# Only the NOT NULL foreign keys appear here: a nullable ``SET NULL`` column is
# *supposed* to end up null when its parent goes, so counting it would report
# correct behaviour as damage.
_RELATIONSHIPS = (
    (CourseOffering, "course_id", Course),
    (ContentItemMedia, "content_item_id", ContentItem),
    (ContentItemMedia, "media_asset_id", MediaAsset),
    (ContentPublication, "content_item_id", ContentItem),
    (ContentPublicationMedia, "publication_id", ContentPublication),
)


def _fingerprint(values: list[str]) -> str:
    """A stable, order-independent digest of a set of identifiers.

    Sorted before hashing because row order is not preserved across a dump and
    restore, and a fingerprint that changed with it would flag every migration
    as broken.
    """
    joined = "\n".join(sorted(values)).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()[:16]


def _isoformat(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _count(session: AsyncSession, model: Any) -> int:
    return int((await session.scalar(select(func.count()).select_from(model))) or 0)


async def _grouped(session: AsyncSession, model: Any, column: Any) -> dict[str, int]:
    rows = await session.execute(select(column, func.count()).group_by(column))
    # ``str(getattr(key, "value", key))`` because an enum reads as
    # ``ContentStatus.draft`` on one engine and ``draft`` on another; the value
    # is what has to match across the move, not the repr.
    return {str(getattr(key, "value", key)): int(count) for key, count in rows.all()}


async def _time_bounds(session: AsyncSession, model: Any) -> dict[str, str | None]:
    """Earliest and latest ``created_at``.

    A timezone dropped in transit shows up here as a whole-hour shift on both
    ends — the cheapest way to catch the tz-naive failure mode, which changes
    no row count and so is invisible everywhere else in this report.
    """
    row = (
        await session.execute(
            select(func.min(model.created_at), func.max(model.created_at))
        )
    ).one()
    return {"earliest": _isoformat(row[0]), "latest": _isoformat(row[1])}


async def _orphans(session: AsyncSession, child: Any, fk_name: str, parent: Any) -> int:
    """Child rows whose foreign key points at a parent that is not there."""
    foreign_key = getattr(child, fk_name)
    missing = (
        select(func.count())
        .select_from(child)
        .where(foreign_key.is_not(None))
        .where(~select(parent.id).where(parent.id == foreign_key).exists())
    )
    return int((await session.scalar(missing)) or 0)


async def collect(session: AsyncSession) -> dict[str, Any]:
    """Build the full report. Runs only SELECTs."""
    report: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "tables": {},
        "breakdowns": {},
        "time_bounds": {},
        "orphans": {},
        "fingerprints": {},
        "integrity": {},
    }

    for model in TABLES:
        report["tables"][model.__tablename__] = await _count(session, model)

    report["breakdowns"] = {
        "content_items_by_status": await _grouped(
            session, ContentItem, ContentItem.status
        ),
        "content_items_by_platform": await _grouped(
            session, ContentItem, ContentItem.platform
        ),
        "publications_by_status": await _grouped(
            session, ContentPublication, ContentPublication.status
        ),
        "media_assets_by_source": await _grouped(session, MediaAsset, MediaAsset.source),
        "social_accounts_by_platform": await _grouped(
            session, SocialAccount, SocialAccount.platform
        ),
    }

    for model in (User, ContentItem, MediaAsset, ContentPublication):
        report["time_bounds"][model.__tablename__] = await _time_bounds(session, model)

    for child, fk_name, parent in _RELATIONSHIPS:
        report["orphans"][f"{child.__tablename__}.{fk_name}"] = await _orphans(
            session, child, fk_name, parent
        )

    # Identity without disclosure: the set of users, items and assets must come
    # out the same set, but the report must not name any of them.
    user_ids = [str(row) for row in (await session.scalars(select(User.id))).all()]
    item_ids = [str(row) for row in (await session.scalars(select(ContentItem.id))).all()]
    checksums = [
        str(row) for row in (await session.scalars(select(MediaAsset.checksum))).all()
    ]
    report["fingerprints"] = {
        "user_ids": _fingerprint(user_ids),
        "content_item_ids": _fingerprint(item_ids),
        # The bytes themselves. A BLOB silently truncated by a MySQL column too
        # small for it (plain BLOB caps at 64 KB; these images run to 10 MB)
        # changes nothing else in this report — not the row count, not the
        # byte_size column — so the stored checksums are where it surfaces.
        "media_checksums": _fingerprint(checksums),
    }

    # ``byte_size`` is what the application recorded at ingest; LENGTH(data) is
    # what the database actually holds. They agree on the source. If they stop
    # agreeing on the target, the images were truncated in transit.
    recorded = int((await session.scalar(select(func.sum(MediaAsset.byte_size)))) or 0)
    stored = int(
        (await session.scalar(select(func.sum(func.length(MediaAsset.data))))) or 0
    )
    report["integrity"] = {
        "media_bytes_recorded": recorded,
        "media_bytes_stored": stored,
        "media_bytes_match": recorded == stored,
    }

    return report


def compare(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Differences that mean the migration lost or corrupted something.

    Returns an empty list when the two reports agree. ``generated_at`` is
    ignored, for the obvious reason.
    """
    problems: list[str] = []

    for table, count in before["tables"].items():
        moved = after["tables"].get(table)
        if moved != count:
            problems.append(f"{table}: {count} rows before, {moved} after")

    for group, expected in before["breakdowns"].items():
        actual = after["breakdowns"].get(group, {})
        if actual != expected:
            problems.append(f"{group}: {expected} before, {actual} after")

    for key, digest in before["fingerprints"].items():
        if after["fingerprints"].get(key) != digest:
            problems.append(
                f"{key}: fingerprint changed — the rows are not the same set"
            )

    for key, count in after["orphans"].items():
        if count > 0:
            problems.append(f"{key}: {count} orphaned rows after migration")

    if not after["integrity"]["media_bytes_match"]:
        problems.append(
            "media bytes: stored length no longer matches the recorded byte_size "
            "— images were truncated (check the BLOB column type)"
        )

    for table, bounds in before["time_bounds"].items():
        if after["time_bounds"].get(table) != bounds:
            problems.append(
                f"{table}: created_at range moved "
                f"({bounds} → {after['time_bounds'].get(table)}) — timezone lost?"
            )

    return problems
