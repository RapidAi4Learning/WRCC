"""Shared test fixtures.

Unit tests run against an in-memory aiosqlite database (zero infrastructure);
the models use portable types (Uuid, JSON-with-JSONB-variant) so the same ORM
layer works on Postgres in production.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.auth.rate_limit import get_rate_limiter
from app.config import Settings, get_settings
from app.db import models  # noqa: F401 - registers tables on Base.metadata
from app.db.base import Base, get_session
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Keep the process-local rate-limit state isolated between tests."""
    get_rate_limiter().reset()


def make_settings(**overrides) -> Settings:
    """Deterministic settings decoupled from any local .env file."""
    defaults: dict = {
        "_env_file": None,
        "auth_secret": "test-secret-key-at-least-32-bytes-long",
    }
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def db_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """In-memory aiosqlite database shared across sessions via StaticPool."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_sessionmaker) -> AsyncIterator[AsyncSession]:
    async with db_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_sessionmaker) -> AsyncIterator[AsyncClient]:
    """App-level HTTP client wired to the in-memory test database."""
    app = create_app()

    async def _test_session() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _test_session
    # Zero-arg closure: FastAPI would otherwise map **kwargs to a query param.
    app.dependency_overrides[get_settings] = lambda: make_settings()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
