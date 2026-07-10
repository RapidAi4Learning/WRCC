"""Admin seed: env-driven credentials, idempotent, fails fast when missing."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import app.db.seed as seed_module
from app.db.models import User
from app.db.seed import SeedConfigError, seed_admin
from tests.conftest import make_settings


@pytest.fixture
def seeded_env(db_sessionmaker, monkeypatch: pytest.MonkeyPatch):
    settings = make_settings(
        admin_email="admin@wrcc.local", admin_password="a-strong-password"
    )
    monkeypatch.setattr(seed_module, "get_settings", lambda: settings)
    monkeypatch.setattr(seed_module, "get_sessionmaker", lambda: db_sessionmaker)
    return db_sessionmaker


async def test_seed_requires_env_credentials(
    db_sessionmaker, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seed_module, "get_settings", lambda: make_settings())
    with pytest.raises(SeedConfigError, match="ADMIN_EMAIL and ADMIN_PASSWORD"):
        await seed_admin()


async def test_seed_creates_admin_once(seeded_env) -> None:
    assert await seed_admin() is True
    # Second run is a no-op, not a duplicate.
    assert await seed_admin() is False

    async with seeded_env() as session:
        users = (await session.execute(select(User))).scalars().all()
    assert len(users) == 1
    assert users[0].email == "admin@wrcc.local"
    # Password is stored hashed, never in the clear.
    assert users[0].password_hash != "a-strong-password"
    assert users[0].password_hash.startswith("$argon2")
