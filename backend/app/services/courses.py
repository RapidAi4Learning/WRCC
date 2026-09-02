"""HITL review side of the catalog sync: approve applies, reject discards."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db.enums import ScraperRunStatus
from app.db.models import ScraperRun
from app.scraper.repository import CatalogRepository, ScraperRunRepository
from app.scraper.selection import count_entries, filter_changeset


class RunNotFoundError(LookupError):
    pass


class InvalidRunTransitionError(RuntimeError):
    pass


def assert_reviewable(run: ScraperRun) -> None:
    if run.status != ScraperRunStatus.pending:
        raise InvalidRunTransitionError(
            f"Run is '{run.status.value}'; only a pending run can be reviewed."
        )


class CourseSyncReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._runs = ScraperRunRepository(session)
        self._catalog = CatalogRepository(session)

    async def _get_run(self, run_id: uuid.UUID) -> ScraperRun:
        run = await self._runs.get(run_id)
        if run is None:
            raise RunNotFoundError(f"Sync run {run_id} not found.")
        return run

    async def approve(
        self,
        run_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        skipped: Mapping[str, Iterable[str]] | None = None,
    ) -> ScraperRun:
        """Apply the staged changeset to the live catalog — the only write path.

        ``skipped`` names entries the reviewer unticked. They are filtered out
        of the run's own changeset here, so what gets written is always what the
        crawl staged, minus what a human said no to. The run keeps the full
        changeset: it is the record of what the crawl saw, and the audit entry
        carries what was actually applied and what was passed over.
        """
        run = await self._get_run(run_id)
        assert_reviewable(run)

        staged = run.changeset or {}
        applied = filter_changeset(staged, skipped)
        await self._catalog.apply_changeset(applied)
        run.status = ScraperRunStatus.approved
        run.reviewed_by = actor_id
        run.reviewed_at = dt.datetime.now(dt.UTC)
        record_audit(
            self._session,
            actor_id=actor_id,
            action="catalog_sync_approved",
            entity_type="scraper_run",
            entity_id=run.id,
            payload_diff={
                "applied": applied.get("summary"),
                "staged": staged.get("summary"),
                "skipped": {
                    section: list(codes)
                    for section, codes in (skipped or {}).items()
                    if codes
                },
                "skipped_count": count_entries(staged) - count_entries(applied),
            },
        )
        await self._session.commit()
        return run

    async def reject(
        self, run_id: uuid.UUID, *, actor_id: uuid.UUID, reason: str | None = None
    ) -> ScraperRun:
        run = await self._get_run(run_id)
        assert_reviewable(run)

        run.status = ScraperRunStatus.rejected
        run.reviewed_by = actor_id
        run.reviewed_at = dt.datetime.now(dt.UTC)
        if reason:
            run.error = reason
        record_audit(
            self._session,
            actor_id=actor_id,
            action="catalog_sync_rejected",
            entity_type="scraper_run",
            entity_id=run.id,
            payload_diff={"reason": reason} if reason else None,
        )
        await self._session.commit()
        return run
