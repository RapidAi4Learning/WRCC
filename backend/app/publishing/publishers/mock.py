"""Deterministic offline publisher (PUBLISH_MOCK=true, the default).

Keeps the app's "boots with zero credentials" property (D3): the entire publish
path — preflight, attempt rows, state transition, audit — is exercised without
a Meta or LinkedIn app existing. Same role ``MockLLMClient`` plays for
generation.
"""

from __future__ import annotations

import hashlib

from app.db.enums import ContentPlatform
from app.publishing.publishers.base import (
    PublishRequest,
    PublishResult,
)

_PERMALINK_TEMPLATES: dict[ContentPlatform, str] = {
    ContentPlatform.facebook: "https://www.facebook.com/{post_id}",
    ContentPlatform.instagram: "https://www.instagram.com/p/{post_id}/",
    ContentPlatform.linkedin: "https://www.linkedin.com/feed/update/{post_id}",
}


class MockPublisher:
    """Returns a stable fake post id derived from the account and the text."""

    def __init__(self, platform: ContentPlatform) -> None:
        self._platform = platform

    async def publish(self, request: PublishRequest) -> PublishResult:
        digest = hashlib.sha256(
            f"{self._platform.value}|{request.account.external_id}|{request.text}".encode()
        ).hexdigest()[:16]
        post_id = f"{request.account.external_id}_{digest}"
        template = _PERMALINK_TEMPLATES[self._platform]
        return PublishResult(
            external_post_id=post_id, permalink=template.format(post_id=post_id)
        )

    async def verify(self, account) -> None:
        """Offline connections are always healthy."""
        return None
