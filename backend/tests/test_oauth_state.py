"""Signed OAuth state: the CSRF guard on the connect flow."""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
import pytest

from app.auth.security import create_access_token
from app.publishing.state import (
    STATE_TTL_SECONDS,
    OAuthStateError,
    sign_state,
    verify_state,
)
from tests.conftest import make_settings

USER_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def test_state_round_trips_the_user_id() -> None:
    settings = make_settings()
    state = sign_state(user_id=USER_ID, provider="meta", settings=settings)
    assert verify_state(state, provider="meta", settings=settings) == USER_ID


def test_two_states_differ_even_in_the_same_second() -> None:
    settings = make_settings()
    now = dt.datetime.now(dt.UTC)
    first = sign_state(user_id=USER_ID, provider="meta", settings=settings, now=now)
    second = sign_state(user_id=USER_ID, provider="meta", settings=settings, now=now)
    assert first != second  # the jti nonce


def test_state_for_one_provider_cannot_finish_another() -> None:
    settings = make_settings()
    state = sign_state(user_id=USER_ID, provider="meta", settings=settings)
    with pytest.raises(OAuthStateError, match="different network"):
        verify_state(state, provider="linkedin", settings=settings)


def test_expired_state_is_rejected() -> None:
    settings = make_settings()
    issued = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=STATE_TTL_SECONDS + 60)
    state = sign_state(user_id=USER_ID, provider="meta", settings=settings, now=issued)
    with pytest.raises(OAuthStateError, match="expired"):
        verify_state(state, provider="meta", settings=settings)


def test_tampered_state_is_rejected() -> None:
    settings = make_settings()
    state = sign_state(user_id=USER_ID, provider="meta", settings=settings)
    head, _, tail = state.rpartition(".")
    with pytest.raises(OAuthStateError, match="not valid"):
        verify_state(f"{head}.{tail[::-1]}", provider="meta", settings=settings)


def test_state_signed_with_another_secret_is_rejected() -> None:
    state = sign_state(
        user_id=USER_ID,
        provider="meta",
        settings=make_settings(auth_secret="a-completely-different-secret-key!!"),
    )
    with pytest.raises(OAuthStateError):
        verify_state(state, provider="meta", settings=make_settings())


def test_a_session_token_cannot_be_replayed_as_state() -> None:
    # Both are HS256 over auth_secret; only the audience separates them. A
    # stolen session cookie must not be usable to authorise a connection.
    settings = make_settings()
    session_token = create_access_token(user_id=USER_ID, settings=settings)
    with pytest.raises(OAuthStateError):
        verify_state(session_token, provider="meta", settings=settings)


def test_state_cannot_be_replayed_as_a_session_token() -> None:
    from app.auth.security import TokenError, decode_access_token

    settings = make_settings()
    state = sign_state(user_id=USER_ID, provider="meta", settings=settings)
    with pytest.raises(TokenError):
        decode_access_token(state, settings=settings)


def test_state_without_a_subject_is_rejected() -> None:
    settings = make_settings()
    forged = jwt.encode(
        {
            "provider": "meta",
            "exp": int((dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)).timestamp()),
            "iss": settings.jwt_issuer,
            "aud": "wrcc-oauth-state",
        },
        settings.auth_secret,
        algorithm="HS256",
    )
    with pytest.raises(OAuthStateError):
        verify_state(forged, provider="meta", settings=settings)
