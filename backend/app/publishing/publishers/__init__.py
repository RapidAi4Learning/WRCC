"""Publisher selection: mock unless PUBLISH_MOCK=false (mirrors get_llm_client)."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.db.enums import ContentPlatform
from app.publishing.publishers.base import (
    AccountVerifier,
    Publisher,
    PublishError,
    PublishRequest,
    PublishResult,
    ResolvedAccount,
)
from app.publishing.publishers.facebook import FacebookPublisher
from app.publishing.publishers.instagram import InstagramPublisher
from app.publishing.publishers.linkedin import LinkedInPublisher
from app.publishing.publishers.mock import MockPublisher

__all__ = [
    "AccountVerifier",
    "Publisher",
    "PublishError",
    "PublishRequest",
    "PublishResult",
    "ResolvedAccount",
    "get_publisher",
    "get_verifier",
]


_LIVE: dict[ContentPlatform, type] = {
    ContentPlatform.facebook: FacebookPublisher,
    ContentPlatform.instagram: InstagramPublisher,
    ContentPlatform.linkedin: LinkedInPublisher,
}


def get_publisher(
    platform: ContentPlatform,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Publisher:
    """Return the publisher for ``platform`` — mock unless PUBLISH_MOCK=false."""
    if settings.publish_mock:
        return MockPublisher(platform)
    return _LIVE[platform](settings, transport=transport)


def get_verifier(
    platform: ContentPlatform,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AccountVerifier:
    """The same classes, viewed through the narrower liveness-check protocol."""
    if settings.publish_mock:
        return MockPublisher(platform)
    return _LIVE[platform](settings, transport=transport)
