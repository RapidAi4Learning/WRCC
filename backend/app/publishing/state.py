"""Signed OAuth state — CSRF protection for the connect flow.

A JWT rather than a database row: it is short-lived and there is no table to
clean up. It carries a **different audience** from the session token so neither
can be replayed as the other — a session cookie presented as `state` must not
authorise a connection, and vice versa.

It is *not* single-use. The `jti` is a nonce for uniqueness, not a replay
record: nothing stores or checks it, so the same state can be presented twice
inside its TTL. That is harmless only because a replay still needs a fresh
authorization `code`, and both providers burn a code on first use — so the
second callback dies at the exchange. Adding a real single-use check would mean
somewhere to keep spent ids; say so here rather than implying a guarantee the
code does not make.

The callback checks this *and* the session cookie. State alone would prove the
flow started here, not that the browser finishing it is still logged in.
"""

from __future__ import annotations

import datetime as dt
import uuid

import jwt

from app.config import Settings

_ALGORITHM = "HS256"
_AUDIENCE = "wrcc-oauth-state"
# Long enough to log in at the provider and pick a Page, short enough that a
# leaked URL from a browser history is worthless.
STATE_TTL_SECONDS = 600


class OAuthStateError(ValueError):
    """Raised when the returned state is missing, expired, or does not match."""


def sign_state(
    *,
    user_id: uuid.UUID,
    provider: str,
    settings: Settings,
    now: dt.datetime | None = None,
) -> str:
    now = now or dt.datetime.now(dt.UTC)
    payload = {
        "sub": str(user_id),
        "provider": provider,
        # A nonce so two connects started in the same second differ.
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(seconds=STATE_TTL_SECONDS)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": _AUDIENCE,
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=_ALGORITHM)


def verify_state(state: str, *, provider: str, settings: Settings) -> uuid.UUID:
    """Return the user id that started this flow, or raise ``OAuthStateError``."""
    try:
        payload = jwt.decode(
            state,
            settings.auth_secret,
            algorithms=[_ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=_AUDIENCE,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise OAuthStateError("The connection request expired. Try again.") from exc
    except jwt.InvalidTokenError as exc:
        raise OAuthStateError("The connection request was not valid.") from exc

    # A state minted for Meta must not complete a LinkedIn connection.
    if payload.get("provider") != provider:
        raise OAuthStateError("The connection request was for a different network.")
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise OAuthStateError("The connection request was not valid.") from exc
