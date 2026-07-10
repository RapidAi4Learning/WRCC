"""The login failure path must always run argon2 (user-enumeration defense)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException, Response

import app.auth.router as auth_router
from app.auth.router import LoginRequest, login
from app.auth.security import dummy_password_hash, hash_password
from app.db.models import User
from tests.conftest import make_settings


class FakeResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class FakeSession:
    def __init__(self, value: object | None) -> None:
        self._value = value

    async def execute(self, _statement: object) -> FakeResult:
        return FakeResult(self._value)


async def test_login_runs_password_verify_even_for_unknown_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified_hashes: list[str] = []

    def spy(plain: str, password_hash: str) -> bool:
        verified_hashes.append(password_hash)
        return False

    monkeypatch.setattr(auth_router, "verify_password", spy)

    # Unknown email: verify still runs, against the dummy hash.
    with pytest.raises(HTTPException) as exc:
        await login(
            LoginRequest(email="nobody@wrcc.local", password="whatever"),
            Response(),
            session=FakeSession(None),  # type: ignore[arg-type]
            settings=make_settings(),
        )
    assert exc.value.status_code == 401
    assert verified_hashes == [dummy_password_hash()]

    # Known user with a wrong password: verify runs against the real hash.
    user = User(
        email="admin@wrcc.local",
        password_hash=hash_password("real-password"),
        display_name="Admin",
        is_active=True,
    )
    with pytest.raises(HTTPException) as exc:
        await login(
            LoginRequest(email=user.email, password="wrong"),
            Response(),
            session=FakeSession(user),  # type: ignore[arg-type]
            settings=make_settings(),
        )
    assert exc.value.status_code == 401
    assert verified_hashes == [dummy_password_hash(), user.password_hash]
