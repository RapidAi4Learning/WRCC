"""Idempotent seed: bootstrap the admin user from ADMIN_EMAIL / ADMIN_PASSWORD.

Run after ``alembic upgrade head``:
    python -m app.db.seed

Fails fast when the env credentials are missing — they are never hardcoded.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.auth.security import hash_password
from app.config import get_settings
from app.db.base import get_sessionmaker
from app.db.models import User


class SeedConfigError(RuntimeError):
    """Raised when the required seed credentials are missing from the env."""


async def seed_admin() -> bool:
    """Create the bootstrap admin if no user with that email exists.

    Returns True if a user was created, False if it already existed.
    """
    settings = get_settings()
    if not settings.admin_email or not settings.admin_password:
        raise SeedConfigError(
            "ADMIN_EMAIL and ADMIN_PASSWORD must be set to seed the admin user."
        )

    async with get_sessionmaker()() as session:
        existing = (
            await session.execute(
                select(User).where(User.email == settings.admin_email)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return False

        session.add(
            User(
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                display_name="Administrator",
                is_active=True,
            )
        )
        await session.commit()
        return True


if __name__ == "__main__":
    created = asyncio.run(seed_admin())
    print("Admin user created." if created else "Admin user already exists.")
