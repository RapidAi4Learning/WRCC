"""Offline connect flow (PUBLISH_MOCK=true, the default).

Lets the whole Settings page — connect, activate, disconnect, reconnect — be
built and demonstrated before a Meta or LinkedIn app exists, and keeps the
callback path under test without a network. The authorize URL points back at
our own callback so the redirect actually completes in a browser.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse

from app.config import Settings
from app.db.enums import ContentPlatform
from app.publishing.oauth.base import (
    ConnectedAccount,
    SocialProvider,
    redirect_uri_for,
)

_MOCK_ACCOUNTS: dict[SocialProvider, list[tuple[ContentPlatform, str, str, str | None]]] = {
    SocialProvider.meta: [
        (
            ContentPlatform.facebook,
            "mock-page-1",
            "Western Riverina Community College",
            None,
        ),
        (ContentPlatform.instagram, "mock-ig-1", "@wrcc", "wrcc"),
    ],
    SocialProvider.linkedin: [
        (
            ContentPlatform.linkedin,
            "mock-org-1",
            "Western Riverina Community College",
            None,
        )
    ],
}


class MockOAuthProvider:
    """Returns deterministic destinations without leaving the process."""

    def __init__(self, provider: SocialProvider, settings: Settings) -> None:
        self.provider = provider
        self._settings = settings

    def authorize_url(self, *, state: str) -> str:
        """Point straight back at our own callback, skipping the consent screen.

        Built through ``redirect_uri_for`` rather than by hand so that a missing
        PUBLIC_API_BASE_URL raises here too. Mock mode does not require that
        setting, and without this the URL would come out relative — the browser
        would resolve it against the frontend origin and 404, which looks like a
        broken connect flow rather than a missing setting.
        """
        callback = redirect_uri_for(
            self.provider, public_api_base_url=self._settings.public_api_base_url
        )
        query = urllib.parse.urlencode({"code": "mock-code", "state": state})
        return f"{callback}?{query}"

    async def exchange(self, code: str) -> list[ConnectedAccount]:
        expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(days=60)
        return [
            ConnectedAccount(
                platform=platform,
                external_id=external_id,
                display_name=display_name,
                handle=handle,
                access_token=f"mock-token-{external_id}",
                # Only LinkedIn tokens expire; Meta Page tokens do not, and the
                # mock mirrors that so the UI's expiry banner is exercised.
                token_expires_at=(
                    expires_at if platform is ContentPlatform.linkedin else None
                ),
                scopes=["mock"],
                metadata={"mock": True},
            )
            for platform, external_id, display_name, handle in _MOCK_ACCOUNTS[
                self.provider
            ]
        ]
