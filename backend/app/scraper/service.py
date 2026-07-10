"""Sync run lifecycle: crawl in background, stage changeset for human review."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db.enums import ScraperRunStatus
from app.db.models import ScraperRun
from app.scraper.diff import build_changeset
from app.scraper.discovery import category_urls, parse_category_page
from app.scraper.fetcher import FetchError, PoliteFetcher
from app.scraper.normalize import build_course_groups
from app.scraper.parser import parse_course_detail
from app.scraper.repository import CatalogRepository, ScraperRunRepository
from app.scraper.types import ScrapedCourseGroup

logger = logging.getLogger(__name__)

Crawler = Callable[[Settings], Awaitable[list[ScrapedCourseGroup]]]


class SyncConflictError(RuntimeError):
    """A run is already running or awaiting review."""


async def crawl_catalog(settings: Settings) -> list[ScrapedCourseGroup]:
    """Crawl every category page, then each course detail page (deduplicated)."""
    entries = []
    detail_cache: dict[str, tuple[str | None, list]] = {}

    async with PoliteFetcher(settings) as fetcher:
        for category, url in category_urls(settings.scraper_base_url).items():
            try:
                html = await fetcher.fetch_text(url)
            except FetchError as exc:
                # Seed drift is a warning, never fatal for the whole crawl.
                logger.warning("Category page failed (%s): %s", category, exc)
                continue
            cards = parse_category_page(html, category=category)
            if not cards:
                logger.warning("Category page yielded no course cards: %s", url)

            for card in cards:
                if not card.detail_url:
                    entries.append((card, None, []))
                    continue
                if card.detail_url not in detail_cache:
                    try:
                        detail_html = await fetcher.fetch_text(card.detail_url)
                        detail_cache[card.detail_url] = parse_course_detail(
                            detail_html,
                            detail_url=card.detail_url,
                            base_url=settings.scraper_base_url,
                        )
                    except FetchError as exc:
                        logger.warning(
                            "Detail page failed (%s): %s", card.detail_url, exc
                        )
                        detail_cache[card.detail_url] = (None, [])
                description, offerings = detail_cache[card.detail_url]
                entries.append((card, description, offerings))

    return build_course_groups(entries)


class SyncService:
    """Owns the background crawl tasks and the run state machine (run side)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        crawler: Crawler | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._crawler: Crawler = crawler or crawl_catalog
        self._background_tasks: set[asyncio.Task] = set()

    async def start_sync(self, session: AsyncSession) -> ScraperRun:
        """Open a run and dispatch the crawl to a background task.

        The run row is committed *before* the task starts so the API response
        (and any status polling) can already see it.
        """
        runs = ScraperRunRepository(session)
        if await runs.has_open_run():
            raise SyncConflictError(
                "A sync is already running or awaiting review."
            )
        run = await runs.create()
        await session.commit()

        task = asyncio.create_task(self._execute(run.id))
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return run

    async def wait_for_pending(self) -> None:
        """Test/shutdown helper: drain in-flight background crawls."""
        if self._background_tasks:
            await asyncio.gather(*tuple(self._background_tasks), return_exceptions=True)

    async def _execute(self, run_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            runs = ScraperRunRepository(session)
            run = await runs.get(run_id)
            if run is None:  # pragma: no cover - the run was just committed
                return
            try:
                groups = await self._crawler(self._settings)
                offerings_found = sum(len(g.offerings) for g in groups)
                if offerings_found == 0:
                    # A catalog site with zero offerings means the crawl or the
                    # DOM contract broke — never stage a mass-deactivation.
                    raise RuntimeError(
                        "Crawl produced zero offerings; refusing to stage a "
                        "destructive changeset."
                    )
                live = await CatalogRepository(session).fetch_live_state()
                run.changeset = build_changeset(groups, live)
                run.courses_found = len(groups)
                run.offerings_found = offerings_found
                run.status = ScraperRunStatus.pending
            except Exception as exc:  # noqa: BLE001 - run must record any failure
                logger.exception("Sync run %s failed", run_id)
                run.status = ScraperRunStatus.failed
                run.error = str(exc)
            run.finished_at = dt.datetime.now(dt.UTC)
            await session.commit()


_sync_service: SyncService | None = None


def get_sync_service() -> SyncService:
    """Process-wide service so background tasks survive across requests."""
    global _sync_service
    if _sync_service is None:
        from app.db.base import get_sessionmaker

        _sync_service = SyncService(get_sessionmaker(), get_settings())
    return _sync_service
