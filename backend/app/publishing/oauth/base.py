"""The OAuth seam shared by the Meta and LinkedIn connect flows.

A single code exchange can yield more than one destination — connecting Meta
returns the Facebook Page *and* the Instagram Business account linked to it —
so ``exchange`` returns a list rather than one account.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, field
from typing import Protocol

from app.db.enums import ContentPlatform


class SocialProvider(enum.StrEnum):
    """An OAuth provider, which is not the same thing as a platform.

    One Meta authorisation covers both Facebook and Instagram, and the redirect
    URI must be identical between the authorize call and the token exchange —
    so the callback is per *provider*, while the UI connects per *platform*.
    """

    meta = "meta"
    linkedin = "linkedin"


PROVIDER_FOR_PLATFORM: dict[ContentPlatform, SocialProvider] = {
    ContentPlatform.facebook: SocialProvider.meta,
    ContentPlatform.instagram: SocialProvider.meta,
    ContentPlatform.linkedin: SocialProvider.linkedin,
}


class OAuthError(RuntimeError):
    """A connect flow failed.

    Carries only the provider's description — never a code, token, or secret —
    because this message is shown to the browser via the `?error=` redirect.
    """


@dataclass(frozen=True, slots=True)
class ConnectedAccount:
    """One destination discovered during a code exchange."""

    platform: ContentPlatform
    external_id: str
    display_name: str
    access_token: str
    handle: str | None = None
    refresh_token: str | None = None
    token_expires_at: dt.datetime | None = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class OAuthProvider(Protocol):
    provider: SocialProvider

    def authorize_url(self, *, state: str) -> str:
        """The provider's consent-screen URL to redirect the browser to."""
        ...

    async def exchange(self, code: str) -> list[ConnectedAccount]:
        """Trade the authorization code for every destination it unlocks."""
        ...


def redirect_uri_for(provider: SocialProvider, *, public_api_base_url: str) -> str:
    """The callback URL, which must match what is registered with the provider.

    Built from configuration rather than from the incoming request: the request
    may arrive through a proxy under an internal hostname, and a mismatch here
    is rejected by the provider with a famously unhelpful error.
    """
    if not public_api_base_url:
        raise OAuthError(
            "PUBLIC_API_BASE_URL is not set, so the redirect URI cannot be built."
        )
    return f"{public_api_base_url.rstrip('/')}/api/social/{provider.value}/callback"
