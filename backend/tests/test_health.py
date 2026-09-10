"""Liveness and readiness endpoints.

Two endpoints rather than one, because a migration cutover needs to tell two
different failures apart: the process is gone, versus the process is up but
pointed at a database it cannot reach.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_health_is_liveness_only_and_never_fails_on_the_database(
    client: AsyncClient,
) -> None:
    """`/api/health` is the platform healthcheck — it must not depend on the DB.

    Railway restarts a container whose healthcheck fails, so wiring a database
    round-trip into this one would turn a brief connection blip into a restart
    loop. Readiness is what carries that signal.
    """
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "database" not in body


async def test_ready_reports_the_database_when_it_answers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stubbed for the same reason the failure cases are.

    ``check_pool_health`` probes the *global* engine built from settings, not
    the in-memory database the test client is wired to, so leaving it real here
    would assert that a production Postgres is reachable from the test run.
    What this endpoint owns is the mapping from that answer to a status code.
    """

    async def _healthy() -> bool:
        return True

    monkeypatch.setattr("app.main.check_pool_health", _healthy)

    response = await client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "up"}


async def test_ready_is_503_when_the_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `curl -f` during cutover has to fail when the DB is not answering."""

    async def _broken() -> bool:
        raise OSError("connection refused")

    monkeypatch.setattr("app.main.check_pool_health", _broken)

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "down"}


async def test_ready_never_leaks_connection_details(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure reason names a host, a user, and sometimes a password.

    This endpoint is unauthenticated, so the body may say *that* the database
    is down and nothing more.
    """

    async def _broken() -> bool:
        raise OSError(
            'connection to server at "db.internal" (10.0.0.7), port 5432 '
            'failed: password authentication failed for user "postgres"'
        )

    monkeypatch.setattr("app.main.check_pool_health", _broken)

    response = await client.get("/api/health/ready")

    serialized = response.text
    for secret in ("db.internal", "10.0.0.7", "5432", "postgres", "password"):
        assert secret not in serialized


async def test_ready_needs_no_session(client: AsyncClient) -> None:
    """Uptime monitors cannot log in — the endpoint stays public."""
    assert (await client.get("/api/health/ready")).status_code in (200, 503)


# ── root ──


async def test_the_bare_url_answers_instead_of_404ing(client: AsyncClient) -> None:
    """Opening the API's domain has to look alive.

    FastAPI serves nothing at `/` by default, so the first thing anyone sees
    when they paste the API's hostname into a browser is a 404 — which reads as
    a broken deployment even when every route below it is healthy.
    """
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_root_points_at_the_two_urls_worth_knowing(
    client: AsyncClient,
) -> None:
    """It exists to answer "is it up, and where do I look next"."""
    body = (await client.get("/")).json()

    assert body["docs"] == "/docs"
    assert body["health"] == "/api/health/ready"


async def test_root_touches_no_database(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is the URL bots and uptime pings hit most.

    Making it query the database would put avoidable load on a pool of three
    connections on shared hosting. Readiness is the endpoint that pays that
    cost, deliberately and only when asked.
    """

    async def _explode() -> bool:
        raise AssertionError("the root endpoint must not check the database")

    monkeypatch.setattr("app.main.check_pool_health", _explode)

    assert (await client.get("/")).status_code == 200


async def test_root_leaks_no_configuration(client: AsyncClient) -> None:
    """It is public and unauthenticated, so it says nothing about the host."""
    serialized = (await client.get("/")).text

    for leaked in ("postgres", "localhost", "secret", "key", "password"):
        assert leaked not in serialized.lower()
