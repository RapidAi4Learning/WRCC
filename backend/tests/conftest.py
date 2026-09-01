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


# A fixed Fernet key so encryption round-trips are deterministic in tests.
# urlsafe-base64 of b"wrcc-test-token-key-32-bytes!!!!" (exactly 32 bytes).
TEST_TOKEN_KEY = "d3JjYy10ZXN0LXRva2VuLWtleS0zMi1ieXRlcyEhISE="


def make_settings(**overrides) -> Settings:
    """Deterministic settings decoupled from any local .env file."""
    defaults: dict = {
        "_env_file": None,
        "auth_secret": "test-secret-key-at-least-32-bytes-long",
        "token_encryption_key": TEST_TOKEN_KEY,
        "media_signing_secret": "test-media-signing-secret",
        "public_api_base_url": "https://api.test",
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


@pytest.fixture
def app(db_sessionmaker):
    """The FastAPI app wired to the in-memory test database.

    Exposed separately from ``client`` so a test can add its own dependency
    override (e.g. different settings) without reaching into the transport.
    """
    application = create_app()

    async def _test_session() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_session] = _test_session
    # Zero-arg closure: FastAPI would otherwise map **kwargs to a query param.
    application.dependency_overrides[get_settings] = lambda: make_settings()
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    """App-level HTTP client wired to the in-memory test database."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


# A token value distinctive enough that a leak into any API response is
# detectable by substring search — see test_publishing_api.
TEST_ACCESS_TOKEN = "live-page-token-must-never-be-serialized"


async def connect_social_account(
    db_sessionmaker,
    platform,
    *,
    external_id: str = "wrcc-page-1",
    display_name: str = "Western Riverina Community College",
    access_token: str = TEST_ACCESS_TOKEN,
    token_expires_at=None,
):
    """Insert an active connected account (stands in for the phase-3 OAuth flow)."""
    from app.publishing.accounts import SocialAccountService

    async with db_sessionmaker() as session:
        account = await SocialAccountService(session, make_settings()).upsert(
            platform=platform,
            external_id=external_id,
            display_name=display_name,
            access_token=access_token,
            actor_id=None,
            token_expires_at=token_expires_at,
            scopes=["pages_manage_posts"],
        )
        await session.commit()
        return account.id


ADMIN_EMAIL = "admin@wrcc.local"
ADMIN_PASSWORD = "correct-horse-battery"


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient, db_sessionmaker) -> AsyncClient:
    """Client with a seeded admin user and an active session cookie."""
    from app.auth.security import hash_password
    from app.db.models import User

    async with db_sessionmaker() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                display_name="Admin",
                is_active=True,
            )
        )
        await session.commit()

    response = await client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return client
