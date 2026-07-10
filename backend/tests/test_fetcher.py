"""Polite fetcher: retries, retryable statuses, and exhaustion."""

from __future__ import annotations

import httpx
import pytest

from app.scraper.fetcher import FetchError, PoliteFetcher
from tests.conftest import make_settings


def _fetcher_with_transport(handler) -> PoliteFetcher:
    settings = make_settings(scraper_request_delay_ms=0, scraper_max_retries=3)
    fetcher = PoliteFetcher(settings)
    # Swap the real network transport for a scripted one.
    fetcher._client = httpx.AsyncClient(  # noqa: SLF001 - test seam
        transport=httpx.MockTransport(handler),
        headers={"User-Agent": settings.scraper_user_agent},
    )
    return fetcher


async def test_fetch_returns_body_and_sends_user_agent() -> None:
    seen_agents: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_agents.append(request.headers["User-Agent"])
        return httpx.Response(200, text="<html>ok</html>")

    async with _fetcher_with_transport(handler) as fetcher:
        assert await fetcher.fetch_text("https://example.test/page") == "<html>ok</html>"
    assert seen_agents == ["WRCC-ContentStudio/1.0 (+https://wrcc.nsw.edu.au)"]


async def test_fetch_retries_transient_errors_then_succeeds() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, text="recovered")

    async with _fetcher_with_transport(handler) as fetcher:
        assert await fetcher.fetch_text("https://example.test/flaky") == "recovered"
    assert calls["count"] == 3


async def test_fetch_gives_up_after_bounded_retries() -> None:
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(503)

    async with _fetcher_with_transport(handler) as fetcher:
        with pytest.raises(FetchError, match="after 3 attempts"):
            await fetcher.fetch_text("https://example.test/down")
    assert calls["count"] == 3


async def test_non_retryable_client_error_fails() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _fetcher_with_transport(handler) as fetcher:
        with pytest.raises(FetchError):
            await fetcher.fetch_text("https://example.test/missing")
