"""Signed public image URLs — the one unauthenticated surface."""

from __future__ import annotations

import datetime as dt
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest

from app.publishing.media import (
    MediaSigningError,
    sign_image_url,
    verify_image_signature,
)
from tests.conftest import make_settings

IMAGE_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _parts(url: str) -> tuple[str, int, str]:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    return parsed.path, int(query["exp"][0]), query["sig"][0]


def test_url_is_absolute_and_points_at_the_public_host() -> None:
    # Meta fetches this from its own servers: a relative path is meaningless.
    url = sign_image_url(make_settings(), image_id=IMAGE_ID)
    assert url.startswith("https://api.test/")
    path, _, _ = _parts(url)
    assert path == f"/api/public/images/{IMAGE_ID}.jpg"


def test_signature_round_trips() -> None:
    settings = make_settings()
    _, expires_at, signature = _parts(sign_image_url(settings, image_id=IMAGE_ID))
    assert verify_image_signature(
        settings, image_id=IMAGE_ID, expires_at=expires_at, signature=signature
    )


def test_signature_is_rejected_for_a_different_image() -> None:
    settings = make_settings()
    _, expires_at, signature = _parts(sign_image_url(settings, image_id=IMAGE_ID))
    assert not verify_image_signature(
        settings, image_id=uuid.uuid4(), expires_at=expires_at, signature=signature
    )


def test_extending_the_expiry_invalidates_the_signature() -> None:
    settings = make_settings()
    _, expires_at, signature = _parts(sign_image_url(settings, image_id=IMAGE_ID))
    assert not verify_image_signature(
        settings,
        image_id=IMAGE_ID,
        expires_at=expires_at + 3600,
        signature=signature,
    )


def test_expired_url_is_rejected() -> None:
    settings = make_settings(media_url_ttl_seconds=60)
    issued = dt.datetime.now(dt.UTC)
    _, expires_at, signature = _parts(
        sign_image_url(settings, image_id=IMAGE_ID, now=issued)
    )
    assert not verify_image_signature(
        settings,
        image_id=IMAGE_ID,
        expires_at=expires_at,
        signature=signature,
        now=issued + dt.timedelta(seconds=61),
    )


def test_url_valid_just_before_expiry() -> None:
    settings = make_settings(media_url_ttl_seconds=60)
    issued = dt.datetime.now(dt.UTC)
    _, expires_at, signature = _parts(
        sign_image_url(settings, image_id=IMAGE_ID, now=issued)
    )
    assert verify_image_signature(
        settings,
        image_id=IMAGE_ID,
        expires_at=expires_at,
        signature=signature,
        now=issued + dt.timedelta(seconds=59),
    )


def test_a_different_secret_cannot_forge_a_url() -> None:
    signed = sign_image_url(make_settings(), image_id=IMAGE_ID)
    _, expires_at, signature = _parts(signed)
    assert not verify_image_signature(
        make_settings(media_signing_secret="a-different-secret"),
        image_id=IMAGE_ID,
        expires_at=expires_at,
        signature=signature,
    )


def test_garbage_signature_is_rejected() -> None:
    settings = make_settings()
    _, expires_at, _ = _parts(sign_image_url(settings, image_id=IMAGE_ID))
    assert not verify_image_signature(
        settings, image_id=IMAGE_ID, expires_at=expires_at, signature="deadbeef"
    )


def test_verification_fails_closed_without_a_secret() -> None:
    assert not verify_image_signature(
        make_settings(media_signing_secret=""),
        image_id=IMAGE_ID,
        expires_at=2_000_000_000,
        signature="anything",
    )


def test_signing_without_a_secret_raises() -> None:
    with pytest.raises(MediaSigningError, match="MEDIA_SIGNING_SECRET"):
        sign_image_url(make_settings(media_signing_secret=""), image_id=IMAGE_ID)


def test_signing_without_a_public_host_explains_why_it_matters() -> None:
    with pytest.raises(MediaSigningError, match="cannot reach"):
        sign_image_url(make_settings(public_api_base_url=""), image_id=IMAGE_ID)


def test_trailing_slash_on_the_base_url_does_not_double_up() -> None:
    url = sign_image_url(
        make_settings(public_api_base_url="https://api.test/"), image_id=IMAGE_ID
    )
    assert "//api/public" not in url


def test_media_host_can_differ_from_the_oauth_host() -> None:
    """An image URL is downloaded; a redirect URI is registered in a dashboard.

    Only the second needs a stable host, so they must be settable apart —
    otherwise every throwaway tunnel restart forces a dashboard edit.
    """
    settings = make_settings(
        public_api_base_url="http://localhost:8000",
        public_media_base_url="https://tunnel.test",
    )

    assert sign_image_url(settings, image_id=IMAGE_ID).startswith("https://tunnel.test/")


def test_media_host_falls_back_to_the_api_host() -> None:
    settings = make_settings(
        public_api_base_url="https://api.test", public_media_base_url=""
    )

    assert sign_image_url(settings, image_id=IMAGE_ID).startswith("https://api.test/")
