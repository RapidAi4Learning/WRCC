"""LinkedIn connect flow: code → token → the organizations you administer.

Two modes, chosen by ``LINKEDIN_AUTHOR_URN`` (decision D6):

* **Organization** (default) — posts as the WRCC Company Page. Needs the
  Community Management API product approved on the LinkedIn developer portal,
  which is a LinkedIn-side gate independent of Meta's App Review.
* **Member** — set the author URN to a ``urn:li:person:…`` and the self-serve
  "Share on LinkedIn" product is enough. Same publisher code, different author.

Unlike Meta, LinkedIn access tokens genuinely expire (60 days), so the refresh
token is stored and the expiry is surfaced in the UI.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse

import httpx

from app.config import Settings
from app.db.enums import ContentPlatform
from app.publishing.oauth.base import (
    ConnectedAccount,
    OAuthError,
    SocialProvider,
    redirect_uri_for,
)

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API_BASE = "https://api.linkedin.com"

ORGANIZATION_SCOPES = [
    "w_organization_social",
    "r_organization_social",
    "rw_organization_admin",
]
MEMBER_SCOPES = ["w_member_social", "openid", "profile"]

_MEMBER_URN_PREFIX = "urn:li:person:"


class LinkedInOAuthProvider:
    provider = SocialProvider.linkedin

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def _member_mode(self) -> bool:
        return self._settings.linkedin_author_urn.startswith(_MEMBER_URN_PREFIX)

    @property
    def _scopes(self) -> list[str]:
        return MEMBER_SCOPES if self._member_mode else ORGANIZATION_SCOPES

    def _redirect_uri(self) -> str:
        return redirect_uri_for(
            self.provider, public_api_base_url=self._settings.public_api_base_url
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport, timeout=self._settings.publish_timeout_seconds
        )

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": self._settings.linkedin_api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def authorize_url(self, *, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._settings.linkedin_client_id,
            "redirect_uri": self._redirect_uri(),
            "state": state,
            "scope": " ".join(self._scopes),
        }
        return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    async def exchange(self, code: str) -> list[ConnectedAccount]:
        token, expires_at, refresh_token = await self._token(code)
        if self._member_mode:
            return [await self._member_account(token, expires_at, refresh_token)]
        return await self._organization_accounts(token, expires_at, refresh_token)

    async def _token(self, code: str) -> tuple[str, dt.datetime | None, str | None]:
        async with self._client() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self._settings.linkedin_client_id,
                    "client_secret": self._settings.linkedin_client_secret,
                    "redirect_uri": self._redirect_uri(),
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        payload = self._json(response, "token exchange")
        token = payload.get("access_token")
        if not token:
            # LinkedIn puts the reason in error_description; the code itself is
            # never echoed back to the browser.
            raise OAuthError(
                str(payload.get("error_description") or "LinkedIn refused the sign-in.")
            )
        expires_in = payload.get("expires_in")
        expires_at = (
            dt.datetime.now(dt.UTC) + dt.timedelta(seconds=int(expires_in))
            if expires_in
            else None
        )
        return str(token), expires_at, payload.get("refresh_token")

    async def _organization_accounts(
        self, token: str, expires_at: dt.datetime | None, refresh_token: str | None
    ) -> list[ConnectedAccount]:
        async with self._client() as client:
            response = await client.get(
                f"{API_BASE}/rest/organizationAcls",
                params={
                    "q": "roleAssignee",
                    "role": "ADMINISTRATOR",
                    "state": "APPROVED",
                    "projection": "(elements*(organization~(localizedName)))",
                },
                headers=self._headers(token),
            )
        payload = self._json(response, "organization lookup")

        accounts: list[ConnectedAccount] = []
        for element in payload.get("elements") or []:
            urn = str(element.get("organization", ""))
            if not urn:
                continue
            decorated = element.get("organization~") or {}
            accounts.append(
                ConnectedAccount(
                    platform=ContentPlatform.linkedin,
                    external_id=urn.rsplit(":", 1)[-1],
                    display_name=str(decorated.get("localizedName") or urn),
                    access_token=token,
                    refresh_token=refresh_token,
                    token_expires_at=expires_at,
                    scopes=list(self._scopes),
                    metadata={"author_urn": urn},
                )
            )
        if not accounts:
            raise OAuthError(
                "That LinkedIn account does not administer any Company Page. "
                "Check the Community Management API product is approved, or set "
                "LINKEDIN_AUTHOR_URN to a urn:li:person: value to post as a member."
            )
        return accounts

    async def _member_account(
        self, token: str, expires_at: dt.datetime | None, refresh_token: str | None
    ) -> ConnectedAccount:
        async with self._client() as client:
            response = await client.get(
                f"{API_BASE}/v2/userinfo", headers=self._headers(token)
            )
        # A missing profile is not fatal: we already know the author URN from
        # configuration, and the display name is cosmetic.
        payload = response.json() if response.is_success else {}
        urn = self._settings.linkedin_author_urn
        return ConnectedAccount(
            platform=ContentPlatform.linkedin,
            external_id=urn.rsplit(":", 1)[-1],
            display_name=str(payload.get("name") or "LinkedIn member"),
            access_token=token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
            scopes=list(self._scopes),
            metadata={"author_urn": urn},
        )

    def _json(self, response: httpx.Response, stage: str) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthError(
                f"LinkedIn returned an unreadable response during the {stage}."
            ) from exc
        if not isinstance(payload, dict):
            raise OAuthError(f"LinkedIn returned an unexpected {stage} response.")
        if response.is_error and payload.get("access_token") is None:
            message = payload.get("error_description") or payload.get("message")
            raise OAuthError(
                str(message or f"LinkedIn rejected the {stage} (HTTP {response.status_code}).")
            )
        return payload
