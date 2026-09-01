"""The connect flow end to end: /connect → provider → /callback → Settings."""

from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient

from app.publishing.state import sign_state
from tests.conftest import TEST_ACCESS_TOKEN, make_settings


def _redirect_query(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


async def _state_for(auth_client: AsyncClient, platform: str) -> str:
    """A state bound to the logged-in user, taken from a real /connect call.

    Note the asymmetry: /connect is addressed by *platform* (what the UI shows
    a card for), while /callback is addressed by *provider* (what actually
    holds the OAuth registration). Connecting `facebook` yields a `meta` state.
    """
    response = await auth_client.get(f"/api/social/{platform}/connect")
    assert response.status_code == 200, response.text
    return _redirect_query(response.json()["authorize_url"])["state"]


# ── /connect ──


async def test_connect_requires_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/social/facebook/connect")).status_code == 401


@pytest.mark.parametrize(
    ("platform", "provider"),
    [("facebook", "meta"), ("instagram", "meta"), ("linkedin", "linkedin")],
)
async def test_connect_maps_each_platform_to_its_provider(
    auth_client: AsyncClient, platform: str, provider: str
) -> None:
    # One Meta authorisation covers Facebook and Instagram, so both platforms
    # must land on the same provider and therefore the same redirect URI.
    response = await auth_client.get(f"/api/social/{platform}/connect")
    assert response.status_code == 200
    assert response.json()["provider"] == provider


async def test_connect_returns_a_stateful_authorize_url(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get("/api/social/linkedin/connect")
    assert _redirect_query(response.json()["authorize_url"])["state"]


async def test_connect_rejects_an_unknown_platform(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/api/social/myspace/connect")).status_code == 422


# ── /callback ──


async def test_callback_requires_auth(client: AsyncClient) -> None:
    # State proves the flow started here; the cookie proves the browser
    # finishing it is still logged in. Both are required.
    response = await client.get(
        "/api/social/meta/callback", params={"code": "x", "state": "y"}
    )
    assert response.status_code == 401


async def test_callback_stores_every_destination_and_redirects_to_settings(
    auth_client: AsyncClient,
) -> None:
    state = await _state_for(auth_client, "facebook")

    response = await auth_client.get(
        "/api/social/meta/callback", params={"code": "mock-code", "state": state}
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("http://localhost:3000/settings")
    assert _redirect_query(location)["connected"] == "meta"

    accounts = (await auth_client.get("/api/social/accounts")).json()
    assert {a["platform"] for a in accounts} == {"facebook", "instagram"}
    assert all(a["is_active"] for a in accounts)


async def test_callback_never_leaks_the_token_it_just_stored(
    auth_client: AsyncClient,
) -> None:
    state = await _state_for(auth_client, "facebook")
    await auth_client.get(
        "/api/social/meta/callback", params={"code": "mock-code", "state": state}
    )
    response = await auth_client.get("/api/social/accounts")
    assert "mock-token" not in response.text
    assert TEST_ACCESS_TOKEN not in response.text


async def test_reconnecting_updates_in_place_instead_of_duplicating(
    auth_client: AsyncClient,
) -> None:
    for _ in range(2):
        state = await _state_for(auth_client, "facebook")
        await auth_client.get(
            "/api/social/meta/callback", params={"code": "mock-code", "state": state}
        )

    accounts = (await auth_client.get("/api/social/accounts")).json()
    assert len(accounts) == 2  # one Page + one Instagram, not four


async def test_callback_with_a_tampered_state_redirects_with_an_error(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get(
        "/api/social/meta/callback", params={"code": "c", "state": "not-a-jwt"}
    )
    assert response.status_code == 303
    assert "not valid" in _redirect_query(response.headers["location"])["error"]
    assert (await auth_client.get("/api/social/accounts")).json() == []


async def test_state_from_one_provider_cannot_finish_another(
    auth_client: AsyncClient,
) -> None:
    state = await _state_for(auth_client, "facebook")

    response = await auth_client.get(
        "/api/social/linkedin/callback", params={"code": "c", "state": state}
    )

    assert "different network" in _redirect_query(response.headers["location"])["error"]
    assert (await auth_client.get("/api/social/accounts")).json() == []


async def test_state_belonging_to_another_user_is_refused(
    auth_client: AsyncClient,
) -> None:
    stranger_state = sign_state(
        user_id=uuid.uuid4(), provider="meta", settings=make_settings()
    )

    response = await auth_client.get(
        "/api/social/meta/callback",
        params={"code": "mock-code", "state": stranger_state},
    )

    error = _redirect_query(response.headers["location"])["error"]
    assert "different user" in error
    assert (await auth_client.get("/api/social/accounts")).json() == []


async def test_provider_denial_is_shown_to_the_operator(
    auth_client: AsyncClient,
) -> None:
    state = await _state_for(auth_client, "facebook")

    response = await auth_client.get(
        "/api/social/meta/callback",
        params={
            "state": state,
            "error": "access_denied",
            "error_description": "The user declined the permissions.",
        },
    )

    assert (
        _redirect_query(response.headers["location"])["error"]
        == "The user declined the permissions."
    )


async def test_callback_without_a_code_does_not_pretend_to_succeed(
    auth_client: AsyncClient,
) -> None:
    state = await _state_for(auth_client, "facebook")
    response = await auth_client.get(
        "/api/social/meta/callback", params={"state": state}
    )
    assert "No authorization code" in _redirect_query(response.headers["location"])["error"]


async def test_callback_redirect_always_targets_the_configured_frontend(
    auth_client: AsyncClient,
) -> None:
    # The destination comes from FRONTEND_ORIGIN, never from the request, so a
    # crafted callback link cannot turn this into an open redirect.
    state = await _state_for(auth_client, "facebook")

    response = await auth_client.get(
        "/api/social/meta/callback",
        params={
            "code": "mock-code",
            "state": state,
            "redirect_uri": "https://evil.test/steal",
        },
    )

    assert response.headers["location"].startswith("http://localhost:3000/settings")


async def test_connected_account_can_then_publish(auth_client: AsyncClient) -> None:
    # The point of the whole flow: connect, then a post actually goes out.
    state = await _state_for(auth_client, "facebook")
    await auth_client.get(
        "/api/social/meta/callback", params={"code": "mock-code", "state": state}
    )

    generated = await auth_client.post(
        "/api/content/generate",
        json={"topic": "First aid", "platforms": ["facebook"]},
    )
    item_id = generated.json()["items"][0]["id"]
    for action in ("submit", "approve"):
        await auth_client.post(f"/api/content/{item_id}/{action}")

    response = await auth_client.post(f"/api/content/{item_id}/publish")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "succeeded"


# ── configuration failures reach the operator ──


async def test_connect_503s_when_the_public_host_is_missing(
    auth_client: AsyncClient, app
) -> None:
    from app.config import get_settings

    # Live mode is caught at startup by the config validator, but mock mode does
    # not require a public host — so the endpoint has to catch it, or the
    # authorize URL comes out relative and 404s against the frontend origin.
    app.dependency_overrides[get_settings] = lambda: make_settings(
        public_api_base_url=""
    )

    response = await auth_client.get("/api/social/facebook/connect")

    assert response.status_code == 503
    assert "PUBLIC_API_BASE_URL" in response.json()["detail"]


async def test_exchange_failure_redirects_with_the_reason(
    auth_client: AsyncClient, app
) -> None:
    import httpx as _httpx

    from app.config import get_settings
    from app.publishing.oauth.base import SocialProvider
    from app.publishing.oauth.meta import MetaOAuthProvider

    state = await _state_for(auth_client, "facebook")

    def handler(request: _httpx.Request) -> _httpx.Response:
        return _httpx.Response(
            400, json={"error": {"code": 100, "message": "Invalid verification code."}}
        )

    live = make_settings(
        publish_mock=False,
        meta_app_id="x",
        meta_app_secret="x",
        linkedin_client_id="x",
        linkedin_client_secret="x",
    )
    app.dependency_overrides[get_settings] = lambda: live
    # The state was minted under mock settings but both share auth_secret, so
    # it still verifies — only the exchange is swapped for a failing one.
    import app.api.publishing as publishing_api

    original = publishing_api.get_oauth_provider
    publishing_api.get_oauth_provider = lambda provider, settings, **kw: (  # type: ignore[assignment]
        MetaOAuthProvider(live, transport=_httpx.MockTransport(handler))
        if provider is SocialProvider.meta
        else original(provider, settings, **kw)
    )
    try:
        response = await auth_client.get(
            "/api/social/meta/callback", params={"code": "bad", "state": state}
        )
    finally:
        publishing_api.get_oauth_provider = original  # type: ignore[assignment]

    assert response.status_code == 303
    assert "Invalid verification code" in _redirect_query(
        response.headers["location"]
    )["error"]
    assert (await auth_client.get("/api/social/accounts")).json() == []
