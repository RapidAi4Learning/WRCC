"""Meta and LinkedIn connect flows, driven by scripted HTTP transports.

No network: each test hands the provider an ``httpx.MockTransport`` that
answers the exact conversation the real API would, following the same seam
pattern as ``test_fetcher.py``.
"""

from __future__ import annotations

import datetime as dt
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.db.enums import ContentPlatform
from app.publishing.meta_graph import (
    MetaAuthError,
    MetaGraphError,
    MetaRateLimitError,
    MetaTransientError,
    raise_for_graph_error,
    redact_access_token,
)
from app.publishing.oauth import SocialProvider, get_oauth_provider
from app.publishing.oauth.base import OAuthError, redirect_uri_for
from app.publishing.oauth.linkedin import LinkedInOAuthProvider
from app.publishing.oauth.meta import MetaOAuthProvider
from app.publishing.oauth.mock import MockOAuthProvider
from tests.conftest import make_settings

LIVE = {
    "publish_mock": False,
    "meta_app_id": "app-123",
    "meta_app_secret": "secret-456",
    "linkedin_client_id": "li-123",
    "linkedin_client_secret": "li-secret",
    "public_api_base_url": "https://api.test",
}


def _live_settings(**overrides):
    return make_settings(**{**LIVE, **overrides})


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# ── Graph error taxonomy ──


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (190, MetaAuthError),
        (200, MetaAuthError),
        (4, MetaRateLimitError),
        (32, MetaRateLimitError),
        (1, MetaTransientError),
        (999, MetaGraphError),
    ],
)
def test_graph_error_codes_map_to_types(code: int, expected: type) -> None:
    with pytest.raises(expected):
        raise_for_graph_error({"error": {"code": code, "message": "nope"}})


def test_clean_payload_raises_nothing() -> None:
    raise_for_graph_error({"data": []})


def test_graph_error_message_has_the_token_redacted() -> None:
    with pytest.raises(MetaGraphError) as excinfo:
        raise_for_graph_error(
            {"error": {"code": 999, "message": "failed for access_token=SECRET123&x=1"}}
        )
    assert "SECRET123" not in str(excinfo.value)
    assert "REDACTED" in str(excinfo.value)


def test_redaction_leaves_everything_else_intact() -> None:
    assert (
        redact_access_token("https://g.test/me?fields=id&access_token=abc123")
        == "https://g.test/me?fields=id&access_token=REDACTED"
    )


# ── redirect URI ──


def test_redirect_uri_is_built_from_config() -> None:
    assert (
        redirect_uri_for(SocialProvider.meta, public_api_base_url="https://api.test/")
        == "https://api.test/api/social/meta/callback"
    )


def test_redirect_uri_without_a_public_host_raises() -> None:
    with pytest.raises(OAuthError, match="PUBLIC_API_BASE_URL"):
        redirect_uri_for(SocialProvider.meta, public_api_base_url="")


# ── Meta authorize URL ──


def test_meta_authorize_url_carries_scopes_and_state() -> None:
    url = MetaOAuthProvider(_live_settings()).authorize_url(state="STATE")
    query = _query(url)
    assert url.startswith("https://www.facebook.com/")
    assert query["state"] == "STATE"
    assert query["client_id"] == "app-123"
    assert query["redirect_uri"] == "https://api.test/api/social/meta/callback"
    assert "pages_manage_posts" in query["scope"]
    assert "instagram_content_publish" in query["scope"]


def test_meta_login_config_replaces_the_scope_list() -> None:
    # Business-type apps reject a bare scope list as "Invalid Scopes" when a
    # Login for Business configuration is in play.
    url = MetaOAuthProvider(
        _live_settings(meta_login_config_id="cfg-1")
    ).authorize_url(state="STATE")
    query = _query(url)
    assert query["config_id"] == "cfg-1"
    assert "scope" not in query


# ── Meta exchange ──


def _meta_transport(
    *,
    pages: list[dict],
    instagram: dict | None = None,
    granted: list[str] | None = None,
    me_name: str = "Julian",
):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(f"{request.method} {path}?{request.url.query.decode()}")
        if path.endswith("/oauth/access_token"):
            params = dict(request.url.params)
            if params.get("grant_type") == "fb_exchange_token":
                return httpx.Response(200, json={"access_token": "LONG-USER-TOKEN"})
            return httpx.Response(200, json={"access_token": "SHORT-USER-TOKEN"})
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": pages})
        if path.endswith("/me/permissions"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"permission": name, "status": "granted"}
                        for name in (granted or [])
                    ]
                },
            )
        if path.endswith("/me"):
            return httpx.Response(200, json={"name": me_name})
        # Page detail lookup for the linked Instagram account.
        return httpx.Response(
            200, json={"instagram_business_account": instagram} if instagram else {}
        )

    return httpx.MockTransport(handler), seen


async def test_meta_exchange_upgrades_to_a_long_lived_token_first() -> None:
    # A Page token derived from a short-lived user token dies within the hour;
    # skipping the upgrade would mean reconnecting daily.
    transport, seen = _meta_transport(
        pages=[{"id": "page-1", "name": "WRCC", "access_token": "PAGE-TOKEN"}]
    )
    await MetaOAuthProvider(_live_settings(), transport=transport).exchange("CODE")

    assert "grant_type=fb_exchange_token" in seen[1]
    assert seen[1].index("fb_exchange_token") > 0
    assert "SHORT-USER-TOKEN" in seen[1]


async def test_meta_exchange_returns_the_page() -> None:
    transport, _ = _meta_transport(
        pages=[{"id": "page-1", "name": "WRCC", "access_token": "PAGE-TOKEN"}]
    )
    accounts = await MetaOAuthProvider(
        _live_settings(), transport=transport
    ).exchange("CODE")

    assert len(accounts) == 1
    page = accounts[0]
    assert page.platform is ContentPlatform.facebook
    assert page.external_id == "page-1"
    assert page.display_name == "WRCC"
    assert page.access_token == "PAGE-TOKEN"
    # Page tokens from a long-lived user token do not expire.
    assert page.token_expires_at is None


async def test_meta_exchange_also_returns_the_linked_instagram_account() -> None:
    transport, _ = _meta_transport(
        pages=[{"id": "page-1", "name": "WRCC", "access_token": "PAGE-TOKEN"}],
        instagram={"id": "ig-9", "username": "wrcc"},
    )
    accounts = await MetaOAuthProvider(
        _live_settings(), transport=transport
    ).exchange("CODE")

    platforms = [account.platform for account in accounts]
    assert platforms == [ContentPlatform.facebook, ContentPlatform.instagram]
    instagram = accounts[1]
    assert instagram.external_id == "ig-9"
    assert instagram.handle == "wrcc"
    assert instagram.display_name == "@wrcc"
    # Instagram publishing authenticates with the parent Page's token.
    assert instagram.access_token == "PAGE-TOKEN"
    assert instagram.metadata["page_id"] == "page-1"


async def test_a_business_owned_page_is_found_even_though_me_accounts_is_empty() -> None:
    """The real WRCC shape: the Page belongs to a Business Portfolio.

    `/me/accounts` lists only personally-held Pages, so an organisation's Page
    comes back empty there and has to be reached via the owning business.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        fields = request.url.params.get("fields", "")
        seen.append(path)
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "USER-TOKEN"})
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": []})
        if path.endswith("/me/businesses"):
            return httpx.Response(200, json={"data": [{"id": "biz-1", "name": "WRCC"}]})
        if path.endswith("/biz-1/owned_pages"):
            # Note: no access_token on this edge — the common real response.
            return httpx.Response(200, json={"data": [{"id": "page-9", "name": "WRCC"}]})
        if path.endswith("/biz-1/client_pages"):
            return httpx.Response(200, json={"data": []})
        if path.endswith("/page-9") and "access_token" in fields:
            return httpx.Response(
                200, json={"name": "WRCC", "access_token": "PAGE-TOKEN"}
            )
        return httpx.Response(200, json={})  # instagram lookup: none linked

    accounts = await MetaOAuthProvider(
        _live_settings(), transport=httpx.MockTransport(handler)
    ).exchange("CODE")

    assert [a.external_id for a in accounts] == ["page-9"]
    assert accounts[0].display_name == "WRCC"
    assert accounts[0].access_token == "PAGE-TOKEN"
    # The personal edge is still tried first — business lookup is the fallback.
    assert any(p.endswith("/me/accounts") for p in seen)


async def test_business_page_discovery_survives_one_business_erroring() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "USER-TOKEN"})
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": []})
        if path.endswith("/me/businesses"):
            return httpx.Response(
                200,
                json={"data": [{"id": "biz-dead"}, {"id": "biz-ok", "name": "WRCC"}]},
            )
        if path.startswith("/v23.0/biz-dead/"):
            return httpx.Response(
                403, json={"error": {"code": 200, "message": "No permission."}}
            )
        if path.endswith("/biz-ok/owned_pages"):
            return httpx.Response(
                200,
                json={"data": [{"id": "p1", "name": "WRCC", "access_token": "T"}]},
            )
        return httpx.Response(200, json={"data": []})

    accounts = await MetaOAuthProvider(
        _live_settings(), transport=httpx.MockTransport(handler)
    ).exchange("CODE")

    # One inaccessible business must not hide a usable Page in another.
    assert [a.external_id for a in accounts] == ["p1"]


async def test_no_pages_blames_the_missing_permission_when_it_is_missing() -> None:
    # "No Pages" has opposite fixes depending on why, so the message has to say
    # which one applies rather than making the operator guess.
    transport, _ = _meta_transport(pages=[], granted=["public_profile"])

    with pytest.raises(OAuthError) as excinfo:
        await MetaOAuthProvider(_live_settings(), transport=transport).exchange("CODE")

    message = str(excinfo.value)
    assert "pages_show_list` is missing" in message
    assert "public_profile" in message  # what *was* granted, verbatim
    assert "Signed in as Julian" in message


async def test_no_pages_blames_business_management_when_that_is_what_is_missing() -> None:
    # The real-world case: every page permission granted, still no Pages,
    # because the Page belongs to a Business Portfolio.
    transport, _ = _meta_transport(
        pages=[], granted=["public_profile", "pages_show_list", "pages_manage_posts"]
    )

    with pytest.raises(OAuthError) as excinfo:
        await MetaOAuthProvider(_live_settings(), transport=transport).exchange("CODE")

    assert "`business_management` is not" in str(excinfo.value)


async def test_no_pages_blames_asset_selection_once_permissions_are_complete() -> None:
    transport, _ = _meta_transport(
        pages=[],
        granted=["public_profile", "pages_show_list", "business_management"],
    )

    with pytest.raises(OAuthError) as excinfo:
        await MetaOAuthProvider(_live_settings(), transport=transport).exchange("CODE")

    assert "not ticked on the asset-selection step" in str(excinfo.value)


async def test_no_pages_still_explains_when_the_diagnostic_calls_fail() -> None:
    # The diagnostic is best-effort: if /me/permissions itself errors we must
    # still raise the original problem, not a secondary failure about it.
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "TOKEN"})
        if path.endswith("/me/accounts"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(400, json={"error": {"code": 1, "message": "nope"}})

    with pytest.raises(OAuthError) as excinfo:
        await MetaOAuthProvider(
            _live_settings(), transport=httpx.MockTransport(handler)
        ).exchange("CODE")

    assert "returned no Pages" in str(excinfo.value)


async def test_meta_exchange_surfaces_a_graph_error_as_an_oauth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": 190, "message": "Invalid code."}}
        )

    with pytest.raises(OAuthError, match="Invalid code"):
        await MetaOAuthProvider(
            _live_settings(), transport=httpx.MockTransport(handler)
        ).exchange("CODE")


async def test_a_page_without_instagram_yields_only_the_page() -> None:
    transport, _ = _meta_transport(
        pages=[{"id": "page-1", "name": "WRCC", "access_token": "PAGE-TOKEN"}],
        instagram=None,
    )
    accounts = await MetaOAuthProvider(
        _live_settings(), transport=transport
    ).exchange("CODE")
    assert [a.platform for a in accounts] == [ContentPlatform.facebook]


# ── LinkedIn ──


def test_linkedin_authorize_url_requests_organization_scopes() -> None:
    url = LinkedInOAuthProvider(_live_settings()).authorize_url(state="STATE")
    query = _query(url)
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization")
    assert query["state"] == "STATE"
    assert "w_organization_social" in query["scope"]


def test_member_mode_requests_the_self_serve_scope_instead() -> None:
    # The escape hatch for D6 when Community Management API access stalls.
    url = LinkedInOAuthProvider(
        _live_settings(linkedin_author_urn="urn:li:person:abc")
    ).authorize_url(state="STATE")
    query = _query(url)
    assert "w_member_social" in query["scope"]
    assert "w_organization_social" not in query["scope"]


def _linkedin_transport(*, token: dict, orgs: dict | None = None, userinfo=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(200, json=token)
        if "organizationAcls" in request.url.path:
            return httpx.Response(200, json=orgs or {"elements": []})
        return httpx.Response(200, json=userinfo or {})

    return httpx.MockTransport(handler)


async def test_linkedin_exchange_stores_the_expiry_and_refresh_token() -> None:
    # Unlike Meta, LinkedIn tokens really do expire — the UI depends on this.
    transport = _linkedin_transport(
        token={
            "access_token": "LI-TOKEN",
            "expires_in": 5_184_000,
            "refresh_token": "LI-REFRESH",
        },
        orgs={
            "elements": [
                {
                    "organization": "urn:li:organization:777",
                    "organization~": {"localizedName": "WRCC"},
                }
            ]
        },
    )

    accounts = await LinkedInOAuthProvider(
        _live_settings(), transport=transport
    ).exchange("CODE")

    assert len(accounts) == 1
    account = accounts[0]
    assert account.external_id == "777"
    assert account.display_name == "WRCC"
    assert account.refresh_token == "LI-REFRESH"
    assert account.metadata["author_urn"] == "urn:li:organization:777"
    assert account.token_expires_at is not None
    assert account.token_expires_at > dt.datetime.now(dt.UTC) + dt.timedelta(days=55)


async def test_linkedin_without_an_administered_page_names_the_way_out() -> None:
    transport = _linkedin_transport(
        token={"access_token": "LI-TOKEN", "expires_in": 100}, orgs={"elements": []}
    )
    with pytest.raises(OAuthError, match="Community Management API"):
        await LinkedInOAuthProvider(_live_settings(), transport=transport).exchange(
            "CODE"
        )


async def test_linkedin_member_mode_uses_the_configured_author_urn() -> None:
    transport = _linkedin_transport(
        token={"access_token": "LI-TOKEN", "expires_in": 100},
        userinfo={"name": "Julian Delgado"},
    )
    accounts = await LinkedInOAuthProvider(
        _live_settings(linkedin_author_urn="urn:li:person:xyz"), transport=transport
    ).exchange("CODE")

    assert accounts[0].external_id == "xyz"
    assert accounts[0].display_name == "Julian Delgado"
    assert accounts[0].metadata["author_urn"] == "urn:li:person:xyz"


async def test_linkedin_token_rejection_surfaces_its_description() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "The authorization code has expired.",
            },
        )

    with pytest.raises(OAuthError, match="authorization code has expired"):
        await LinkedInOAuthProvider(
            _live_settings(), transport=httpx.MockTransport(handler)
        ).exchange("CODE")


async def test_linkedin_non_json_response_is_reported_cleanly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>gateway error</html>")

    with pytest.raises(OAuthError, match="unreadable response"):
        await LinkedInOAuthProvider(
            _live_settings(), transport=httpx.MockTransport(handler)
        ).exchange("CODE")


async def test_linkedin_requests_carry_the_versioning_headers() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(200, json={"access_token": "T", "expires_in": 1})
        return httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "organization": "urn:li:organization:1",
                        "organization~": {"localizedName": "X"},
                    }
                ]
            },
        )

    await LinkedInOAuthProvider(
        _live_settings(linkedin_api_version="202506"),
        transport=httpx.MockTransport(handler),
    ).exchange("CODE")

    api_call = seen[-1]
    assert api_call["LinkedIn-Version"] == "202506"
    assert api_call["X-Restli-Protocol-Version"] == "2.0.0"
    assert api_call["Authorization"] == "Bearer T"


# ── provider selection ──


@pytest.mark.parametrize("provider", list(SocialProvider))
def test_mock_provider_is_selected_by_default(provider: SocialProvider) -> None:
    assert isinstance(
        get_oauth_provider(provider, make_settings()), MockOAuthProvider
    )


def test_live_selection_returns_the_real_providers() -> None:
    settings = _live_settings()
    assert isinstance(
        get_oauth_provider(SocialProvider.meta, settings), MetaOAuthProvider
    )
    assert isinstance(
        get_oauth_provider(SocialProvider.linkedin, settings), LinkedInOAuthProvider
    )


async def test_mock_meta_exchange_yields_a_page_and_an_instagram_account() -> None:
    accounts = await MockOAuthProvider(
        SocialProvider.meta, make_settings()
    ).exchange("code")
    assert [a.platform for a in accounts] == [
        ContentPlatform.facebook,
        ContentPlatform.instagram,
    ]
    # Mirrors reality: Meta Page tokens carry no expiry, LinkedIn's do.
    assert all(a.token_expires_at is None for a in accounts)


async def test_mock_linkedin_exchange_sets_an_expiry() -> None:
    accounts = await MockOAuthProvider(
        SocialProvider.linkedin, make_settings()
    ).exchange("code")
    assert accounts[0].token_expires_at is not None


def test_mock_authorize_url_points_back_at_our_callback() -> None:
    url = MockOAuthProvider(SocialProvider.meta, make_settings()).authorize_url(
        state="STATE"
    )
    assert url.startswith("https://api.test/api/social/meta/callback")
    assert _query(url)["state"] == "STATE"


def test_graph_error_json_is_not_a_dict() -> None:
    # Defensive: a list body must not blow up the error mapper.
    raise_for_graph_error(json.loads("[1, 2]"))


# ── GraphClient transport behaviour (relied on by the phase-4 publishers) ──


async def _graph(handler, **overrides):
    from app.publishing.meta_graph import GraphClient

    return GraphClient(
        _live_settings(**overrides),
        access_token="PAGE-TOKEN",
        transport=httpx.MockTransport(handler),
    )


async def test_graph_get_attaches_the_access_token() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"ok": True})

    client = await _graph(handler)
    assert await client.get("/me", params={"fields": "id"}) == {"ok": True}
    assert seen[0] == {"fields": "id", "access_token": "PAGE-TOKEN"}


async def test_graph_post_sends_a_form_body_with_the_token() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content.decode())
        return httpx.Response(200, json={"id": "page_1"})

    client = await _graph(handler)
    assert await client.post("/page/feed", data={"message": "hi"}) == {"id": "page_1"}
    assert "message=hi" in seen[0]
    assert "access_token=PAGE-TOKEN" in seen[0]


async def test_graph_maps_an_error_body_even_on_a_4xx() -> None:
    # Graph puts the real reason in the body of a 400; raising on status first
    # would throw that away and surface every rejection as an opaque error.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": 190, "message": "Token expired."}}
        )

    client = await _graph(handler)
    with pytest.raises(MetaAuthError, match="Token expired"):
        await client.get("/me")


async def test_graph_non_json_body_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    client = await _graph(handler)
    with pytest.raises(MetaTransientError, match="non-JSON"):
        await client.get("/me")


async def test_graph_error_status_without_a_payload_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"nope": True})

    client = await _graph(handler)
    with pytest.raises(MetaTransientError, match="without an error payload"):
        await client.get("/me")


async def test_graph_non_dict_body_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2, 3])

    client = await _graph(handler)
    with pytest.raises(MetaTransientError, match="unexpected body"):
        await client.get("/me")


# ── exchange edge cases ──


async def test_meta_exchange_without_an_access_token_is_an_oauth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not_a_token": True})

    with pytest.raises(OAuthError, match="did not return an access token"):
        await MetaOAuthProvider(
            _live_settings(), transport=httpx.MockTransport(handler)
        ).exchange("CODE")


async def test_meta_exchange_without_a_long_lived_token_is_an_oauth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("grant_type") == "fb_exchange_token":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"access_token": "SHORT"})

    with pytest.raises(OAuthError, match="long-lived"):
        await MetaOAuthProvider(
            _live_settings(), transport=httpx.MockTransport(handler)
        ).exchange("CODE")


async def test_pages_without_tokens_are_reported_not_stored() -> None:
    transport, _ = _meta_transport(pages=[{"id": "page-1", "name": "WRCC"}])
    with pytest.raises(OAuthError, match="without usable access tokens"):
        await MetaOAuthProvider(_live_settings(), transport=transport).exchange("CODE")


async def test_instagram_lookup_failure_does_not_lose_the_page() -> None:
    # A Page with no linked Business account is normal, and a failed lookup
    # must not cost us the Facebook destination we already resolved.
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/oauth/access_token"):
            return httpx.Response(200, json={"access_token": "T"})
        if path.endswith("/me/accounts"):
            return httpx.Response(
                200,
                json={"data": [{"id": "p1", "name": "WRCC", "access_token": "PT"}]},
            )
        return httpx.Response(400, json={"error": {"code": 100, "message": "nope"}})

    accounts = await MetaOAuthProvider(
        _live_settings(), transport=httpx.MockTransport(handler)
    ).exchange("CODE")

    assert [a.platform for a in accounts] == [ContentPlatform.facebook]


async def test_linkedin_organization_without_a_urn_is_skipped() -> None:
    transport = _linkedin_transport(
        token={"access_token": "T", "expires_in": 10},
        orgs={"elements": [{"organization~": {"localizedName": "Nameless"}}]},
    )
    with pytest.raises(OAuthError, match="does not administer"):
        await LinkedInOAuthProvider(_live_settings(), transport=transport).exchange("C")


async def test_linkedin_token_without_an_expiry_leaves_it_unset() -> None:
    transport = _linkedin_transport(
        token={"access_token": "T"},
        orgs={
            "elements": [
                {
                    "organization": "urn:li:organization:5",
                    "organization~": {"localizedName": "WRCC"},
                }
            ]
        },
    )
    accounts = await LinkedInOAuthProvider(
        _live_settings(), transport=transport
    ).exchange("C")
    assert accounts[0].token_expires_at is None


async def test_linkedin_member_mode_survives_a_failed_profile_lookup() -> None:
    # The author URN comes from configuration; the display name is cosmetic.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/accessToken"):
            return httpx.Response(200, json={"access_token": "T", "expires_in": 10})
        return httpx.Response(403, json={"message": "no profile scope"})

    accounts = await LinkedInOAuthProvider(
        _live_settings(linkedin_author_urn="urn:li:person:xyz"),
        transport=httpx.MockTransport(handler),
    ).exchange("C")

    assert accounts[0].display_name == "LinkedIn member"
    assert accounts[0].external_id == "xyz"


async def test_linkedin_non_dict_response_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[1, 2])

    with pytest.raises(OAuthError, match="unexpected"):
        await LinkedInOAuthProvider(
            _live_settings(), transport=httpx.MockTransport(handler)
        ).exchange("C")
