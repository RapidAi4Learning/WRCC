"""Password hashing (argon2id) and JWT issue/verify (§4a).

Pure functions — no DB or framework coupling — so they unit-test directly.
"""

from __future__ import annotations

import datetime as dt
import uuid

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import Settings

_hasher = PasswordHasher()
_ALGORITHM = "HS256"

# Dummy hash verified on the login failure path when the account is missing or
# inactive, so argon2 always runs and a nonexistent email cannot be
# distinguished from a wrong password by response timing (user enumeration).
_DUMMY_PASSWORD_HASH = _hasher.hash("wrcc-timing-equalizer")


def dummy_password_hash() -> str:
    """Return the constant dummy hash used to equalize failure-path timing."""
    return _DUMMY_PASSWORD_HASH


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, plain)
    except VerifyMismatchError:
        return False
    except Exception:  # noqa: BLE001 - malformed hash is a failed verification
        return False


def create_access_token(
    *, user_id: uuid.UUID, settings: Settings, now: dt.datetime | None = None
) -> str:
    now = now or dt.datetime.now(dt.UTC)
    expire = now + dt.timedelta(minutes=settings.jwt_expires_minutes)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=_ALGORITHM)


class TokenError(ValueError):
    """Raised when a JWT is missing, expired, or invalid."""


def decode_access_token(token: str, *, settings: Settings) -> dict:
    """Decode and validate a JWT; raises TokenError on any failure.

    Validates the signature, expiry, issuer, and audience so a token minted for
    a different issuer/audience is rejected.
    """
    try:
        return jwt.decode(
            token,
            settings.auth_secret,
            algorithms=[_ALGORITHM],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("Token is invalid.") from exc
