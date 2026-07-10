"""Password hashing and JWT issue/verify (pure functions)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app.auth.security import (
    TokenError,
    create_access_token,
    decode_access_token,
    dummy_password_hash,
    hash_password,
    verify_password,
)
from tests.conftest import make_settings


def test_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("s3cret-password")
    assert hashed != "s3cret-password"
    assert verify_password("s3cret-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_verify_tolerates_malformed_hash() -> None:
    assert not verify_password("anything", "not-a-real-argon2-hash")


def test_dummy_hash_is_stable_and_verifiable_shape() -> None:
    assert dummy_password_hash() == dummy_password_hash()
    assert not verify_password("anything", dummy_password_hash())


def test_token_roundtrip_carries_subject() -> None:
    settings = make_settings()
    user_id = uuid.uuid4()
    token = create_access_token(user_id=user_id, settings=settings)
    payload = decode_access_token(token, settings=settings)
    assert payload["sub"] == str(user_id)
    assert payload["iss"] == settings.jwt_issuer
    assert payload["aud"] == settings.jwt_audience


def test_expired_token_is_rejected() -> None:
    settings = make_settings()
    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=settings.jwt_expires_minutes + 5)
    token = create_access_token(user_id=uuid.uuid4(), settings=settings, now=past)
    with pytest.raises(TokenError, match="expired"):
        decode_access_token(token, settings=settings)


def test_token_from_other_issuer_or_audience_is_rejected() -> None:
    settings = make_settings()
    foreign = make_settings(jwt_issuer="someone-else")
    token = create_access_token(user_id=uuid.uuid4(), settings=foreign)
    with pytest.raises(TokenError):
        decode_access_token(token, settings=settings)


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(TokenError):
        decode_access_token("garbage.token.value", settings=make_settings())
