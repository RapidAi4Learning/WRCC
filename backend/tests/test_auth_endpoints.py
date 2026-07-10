"""End-to-end auth flow against the app with an in-memory database."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.db.models import User

EMAIL = "admin@wrcc.local"
PASSWORD = "correct-horse-battery"


async def _seed_user(db_session: AsyncSession, *, active: bool = True) -> User:
    user = User(
        email=EMAIL,
        password_hash=hash_password(PASSWORD),
        display_name="Admin",
        is_active=active,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def test_health_is_public(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_me_without_session_is_401(client: AsyncClient) -> None:
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_login_sets_httponly_cookie_and_me_returns_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_user(db_session)

    response = await client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == EMAIL
    assert body["display_name"] == "Admin"
    set_cookie = response.headers["set-cookie"]
    assert "wrcc_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


@pytest.mark.parametrize(
    ("email", "password", "seed_active"),
    [
        (EMAIL, "wrong-password", True),
        ("nobody@wrcc.local", PASSWORD, True),
        (EMAIL, PASSWORD, False),
    ],
)
async def test_login_rejects_bad_credentials_uniformly(
    client: AsyncClient,
    db_session: AsyncSession,
    email: str,
    password: str,
    seed_active: bool,
) -> None:
    await _seed_user(db_session, active=seed_active)

    response = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 401
    # Uniform response: nothing distinguishes unknown email from wrong password.
    assert response.json()["detail"] == "Invalid email or password."


async def test_logout_clears_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_user(db_session)
    await client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})

    response = await client.post("/api/auth/logout")
    assert response.status_code == 200

    me = await client.get("/api/auth/me")
    assert me.status_code == 401


async def test_login_is_rate_limited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_user(db_session)
    for _ in range(5):
        response = await client.post(
            "/api/auth/login", json={"email": EMAIL, "password": "wrong"}
        )
        assert response.status_code == 401

    response = await client.post(
        "/api/auth/login", json={"email": EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 429
