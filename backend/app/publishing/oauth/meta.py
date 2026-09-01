"""Meta connect flow: code → long-lived user token → Page tokens → IG accounts.

The four-step dance matters. A Page token derived from a *short-lived* user
token expires in about an hour; derived from a long-lived one it effectively
does not expire, which is the difference between reconnecting every day and
reconnecting never. Hence step 2.
"""

from __future__ import annotations

import urllib.parse

import httpx

from app.config import Settings
from app.db.enums import ContentPlatform
from app.publishing.meta_graph import GraphClient, MetaGraphError
from app.publishing.oauth.base import (
    ConnectedAccount,
    OAuthError,
    SocialProvider,
    redirect_uri_for,
)

SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
]


class MetaOAuthProvider:
    provider = SocialProvider.meta

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    def _redirect_uri(self) -> str:
        return redirect_uri_for(
            self.provider, public_api_base_url=self._settings.public_api_base_url
        )

    def authorize_url(self, *, state: str) -> str:
        """Build the Facebook OAuth dialog URL.

        With a Facebook Login for Business ``config_id`` the dialog derives its
        permissions from the dashboard configuration and ``scope`` must be
        omitted — business-type apps reject a bare scope list as "Invalid
        Scopes", which is a genuinely non-obvious trap.
        """
        params = {
            "client_id": self._settings.meta_app_id,
            "redirect_uri": self._redirect_uri(),
            "response_type": "code",
            "state": state,
        }
        if self._settings.meta_login_config_id:
            params["config_id"] = self._settings.meta_login_config_id
        else:
            params["scope"] = ",".join(SCOPES)
        version = self._settings.meta_graph_version
        return (
            f"https://www.facebook.com/{version}/dialog/oauth"
            f"?{urllib.parse.urlencode(params)}"
        )

    async def exchange(self, code: str) -> list[ConnectedAccount]:
        client = GraphClient(self._settings, transport=self._transport)
        try:
            short_lived = await self._short_lived_token(client, code)
            long_lived = await self._long_lived_token(client, short_lived)
            return await self._discover_accounts(long_lived)
        except MetaGraphError as exc:
            raise OAuthError(str(exc)) from exc

    async def _short_lived_token(self, client: GraphClient, code: str) -> str:
        payload = await client.get(
            "/oauth/access_token",
            params={
                "client_id": self._settings.meta_app_id,
                "client_secret": self._settings.meta_app_secret,
                "redirect_uri": self._redirect_uri(),
                "code": code,
            },
        )
        token = payload.get("access_token")
        if not token:
            raise OAuthError("Meta did not return an access token.")
        return str(token)

    async def _long_lived_token(self, client: GraphClient, short_lived: str) -> str:
        payload = await client.get(
            "/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self._settings.meta_app_id,
                "client_secret": self._settings.meta_app_secret,
                "fb_exchange_token": short_lived,
            },
        )
        token = payload.get("access_token")
        if not token:
            raise OAuthError("Meta did not return a long-lived access token.")
        return str(token)

    async def _discover_accounts(self, user_token: str) -> list[ConnectedAccount]:
        client = GraphClient(
            self._settings, access_token=user_token, transport=self._transport
        )
        payload = await client.get(
            "/me/accounts", params={"fields": "id,name,access_token"}
        )
        pages = list(payload.get("data") or [])
        if not pages:
            # `/me/accounts` lists only Pages held personally. A Page owned by a
            # Business Portfolio — which is how any organisation runs one — is
            # invisible there and has to be reached through its owning business.
            pages = await self._pages_via_businesses(client)
        if not pages:
            # "No Pages" has several very different causes, and guessing wastes
            # a round trip through the browser each time. Ask Graph what it
            # actually granted and who authorised, so the message states facts.
            raise OAuthError(await self._explain_no_pages(client))

        accounts: list[ConnectedAccount] = []
        for page in pages:
            page_id = str(page.get("id", ""))
            page_token = str(page.get("access_token", ""))
            if not page_id or not page_token:
                continue
            accounts.append(
                ConnectedAccount(
                    platform=ContentPlatform.facebook,
                    external_id=page_id,
                    display_name=str(page.get("name") or f"Page {page_id}"),
                    access_token=page_token,
                    # No expiry: a Page token minted from a long-lived user
                    # token stays valid until permissions change.
                    token_expires_at=None,
                    scopes=list(SCOPES),
                )
            )
            instagram = await self._instagram_for_page(page_id, page_token)
            if instagram is not None:
                accounts.append(instagram)
        if not accounts:
            raise OAuthError("Meta returned Pages without usable access tokens.")
        return accounts

    async def _pages_via_businesses(self, client: GraphClient) -> list[dict]:
        """Find Pages through the Business Portfolios the user belongs to.

        Best-effort throughout: every step here is a fallback for the common
        case, so a permission error on one business must not abort discovery of
        another. Returns only Pages we could obtain a token for — a Page we
        cannot post as is not a destination.
        """
        try:
            payload = await client.get("/me/businesses", params={"fields": "id,name"})
        except MetaGraphError:
            return []

        seen: dict[str, dict] = {}
        for business in payload.get("data") or []:
            business_id = str(business.get("id") or "")
            if not business_id:
                continue
            # `owned_pages` is the organisation's own Pages; `client_pages` are
            # Pages another business shared with it. Both are publishable.
            for edge in ("owned_pages", "client_pages"):
                try:
                    found = await client.get(
                        f"/{business_id}/{edge}",
                        params={"fields": "id,name,access_token"},
                    )
                except MetaGraphError:
                    continue
                for page in found.get("data") or []:
                    page_id = str(page.get("id") or "")
                    if page_id and page_id not in seen:
                        seen[page_id] = page

        resolved: list[dict] = []
        for page_id, page in seen.items():
            if page.get("access_token"):
                resolved.append(page)
                continue
            # These edges frequently omit the token; ask the Page directly.
            try:
                detail = await client.get(
                    f"/{page_id}", params={"fields": "name,access_token"}
                )
            except MetaGraphError:
                continue
            if detail.get("access_token"):
                resolved.append(
                    {
                        "id": page_id,
                        "name": page.get("name") or detail.get("name"),
                        "access_token": detail["access_token"],
                    }
                )
        return resolved

    async def _explain_no_pages(self, client: GraphClient) -> str:
        """Turn an empty /me/accounts into a message that names the real cause.

        The three causes look identical from the outside and need opposite
        fixes: a permission was never granted, the person genuinely administers
        no Page, or — the usual one with Login for Business — they authorised
        without ticking the Page on the asset-selection step, so the token is
        valid but covers nothing.
        """
        granted: list[str] = []
        who = ""
        try:
            perms = await client.get("/me/permissions")
            granted = sorted(
                str(row.get("permission"))
                for row in (perms.get("data") or [])
                if row.get("status") == "granted"
            )
        except MetaGraphError:
            pass
        try:
            me = await client.get("/me", params={"fields": "name"})
            who = str(me.get("name") or "")
        except MetaGraphError:
            pass

        businesses = ""
        try:
            found = await client.get("/me/businesses", params={"fields": "id,name"})
            businesses = ", ".join(
                str(row.get("name") or row.get("id"))
                for row in (found.get("data") or [])
            )
        except MetaGraphError as exc:
            # The error text itself names the missing permission, which is the
            # single most useful thing we can hand back.
            businesses = f"lookup failed — {exc}"

        parts = ["Meta authorised the app but returned no Pages."]
        if who:
            parts.append(f"Signed in as {who}.")
        parts.append(f"Permissions granted: {', '.join(granted) if granted else 'none'}.")
        parts.append(f"Business portfolios visible: {businesses or 'none'}.")

        if "pages_show_list" not in granted:
            parts.append(
                "`pages_show_list` is missing — add it to the Login for Business "
                "configuration, since permissions come from there and not from "
                "this app's code."
            )
        elif "business_management" not in granted:
            parts.append(
                "`pages_show_list` is granted but `business_management` is not, "
                "and a Page owned by a Business Portfolio is invisible without "
                "it. Add `business_management` to the Login for Business "
                "configuration and reconnect."
            )
        else:
            parts.append(
                "Permissions look complete, so the Page was most likely not "
                "ticked on the asset-selection step — reconnect and select the "
                "WRCC Page when Facebook asks which assets to share."
            )
        return " ".join(parts)

    async def _instagram_for_page(
        self, page_id: str, page_token: str
    ) -> ConnectedAccount | None:
        """Find the Instagram Business account linked to a Page, if any.

        Absence is normal — a Page with no linked Business account simply has
        no Instagram destination — so this never raises.
        """
        client = GraphClient(
            self._settings, access_token=page_token, transport=self._transport
        )
        try:
            payload = await client.get(
                f"/{page_id}",
                params={"fields": "instagram_business_account{id,username}"},
            )
        except MetaGraphError:
            return None
        linked = payload.get("instagram_business_account") or {}
        ig_id = str(linked.get("id", ""))
        if not ig_id:
            return None
        username = linked.get("username")
        return ConnectedAccount(
            platform=ContentPlatform.instagram,
            external_id=ig_id,
            display_name=f"@{username}" if username else f"Instagram {ig_id}",
            handle=str(username) if username else None,
            # Instagram publishing authenticates with the parent Page's token.
            access_token=page_token,
            token_expires_at=None,
            scopes=list(SCOPES),
            metadata={"page_id": page_id},
        )
