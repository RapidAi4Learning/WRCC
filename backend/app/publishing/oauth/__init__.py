"""OAuth provider selection: mock unless PUBLISH_MOCK=false."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.publishing.oauth.base import (
    PROVIDER_FOR_PLATFORM,
    ConnectedAccount,
    OAuthError,
    OAuthProvider,
    SocialProvider,
    redirect_uri_for,
)
from app.publishing.oauth.linkedin import LinkedInOAuthProvider
from app.publishing.oauth.meta import MetaOAuthProvider
from app.publishing.oauth.mock import MockOAuthProvider

__all__ = [
    "PROVIDER_FOR_PLATFORM",
    "ConnectedAccount",
    "OAuthError",
    "OAuthProvider",
    "SocialProvider",
    "get_oauth_provider",
    "redirect_uri_for",
]


def get_oauth_provider(
    provider: SocialProvider,
    settings: Settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OAuthProvider:
    if settings.publish_mock:
        return MockOAuthProvider(provider, settings)
    if provider is SocialProvider.meta:
        return MetaOAuthProvider(settings, transport=transport)
    return LinkedInOAuthProvider(settings, transport=transport)
