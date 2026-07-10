"""Polite async HTML fetcher: request delay, bounded retries, descriptive UA."""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """Raised when a URL cannot be fetched after all retries."""


class PoliteFetcher:
    """Serial fetcher with a politeness delay between requests."""

    def __init__(self, settings: Settings) -> None:
        self._delay_seconds = settings.scraper_request_delay_ms / 1000
        self._max_retries = settings.scraper_max_retries
        self._client = httpx.AsyncClient(
            timeout=settings.scraper_timeout_seconds,
            headers={"User-Agent": settings.scraper_user_agent},
            follow_redirects=True,
        )
        self._has_fetched = False

    async def fetch_text(self, url: str) -> str:
        """GET a page, retrying transient failures with linear backoff."""
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            if self._has_fetched:
                await asyncio.sleep(self._delay_seconds)
            self._has_fetched = True
            try:
                response = await self._client.get(url)
                if response.status_code in _RETRYABLE_STATUS:
                    raise FetchError(f"HTTP {response.status_code} from {url}")
                response.raise_for_status()
                return response.text
            except (httpx.HTTPError, FetchError) as exc:
                last_error = exc
                logger.warning(
                    "Fetch attempt %d/%d failed for %s: %s",
                    attempt,
                    self._max_retries,
                    url,
                    exc,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(self._delay_seconds * attempt)
        raise FetchError(f"Failed to fetch {url} after {self._max_retries} attempts") from (
            last_error
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> PoliteFetcher:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
