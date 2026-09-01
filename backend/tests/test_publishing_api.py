"""Publishing endpoints: auth, status-code contract, and token containment."""

from __future__ import annotations

import datetime as dt

import pytest
from httpx import AsyncClient

from app.db.enums import ContentPlatform
from tests.conftest import TEST_ACCESS_TOKEN, connect_social_account

UNKNOWN_ID = "00000000-0000-0000-0000-000000000000"


async def _approved_item(auth_client: AsyncClient, platform: str = "facebook") -> str:
    """Generate, then walk the item through the HITL workflow to `approved`."""
    response = await auth_client.post(
        "/api/content/generate",
        json={"topic": "First aid enrolments", "platforms": [platform]},
    )
    assert response.status_code == 200, response.text
    item_id = response.json()["items"][0]["id"]
    for action in ("submit", "approve"):
        step = await auth_client.post(f"/api/content/{item_id}/{action}")
        assert step.status_code == 200, step.text
    return item_id


async def _add_image(auth_client: AsyncClient, item_id: str) -> str:
    response = await auth_client.post(
        f"/api/content/{item_id}/images", json={"prompt": "a bright classroom"}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


# ── auth ──


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/social/accounts"),
        ("delete", f"/api/social/accounts/{UNKNOWN_ID}"),
        ("post", f"/api/content/{UNKNOWN_ID}/publish"),
        ("get", f"/api/content/{UNKNOWN_ID}/publish/preflight"),
        ("get", f"/api/content/{UNKNOWN_ID}/publications"),
    ],
)
async def test_publishing_endpoints_require_auth(
    client: AsyncClient, method: str, path: str
) -> None:
    response = await getattr(client, method)(path)
    assert response.status_code == 401


# ── connected accounts ──


async def test_accounts_list_is_empty_before_connecting(
    auth_client: AsyncClient,
) -> None:
    response = await auth_client.get("/api/social/accounts")
    assert response.status_code == 200
    assert response.json() == []


async def test_account_response_never_contains_the_token(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    response = await auth_client.get("/api/social/accounts")
    assert response.status_code == 200
    # Substring search over the raw body: a token must not appear under any
    # key, however a future serializer edit might expose it.
    assert TEST_ACCESS_TOKEN not in response.text
    assert "access_token" not in response.text
    account = response.json()[0]
    assert account["display_name"] == "Western Riverina Community College"
    assert account["is_active"] is True
    assert account["token_expired"] is False


async def test_expired_token_is_reported_to_the_client(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    await connect_social_account(
        db_sessionmaker,
        ContentPlatform.linkedin,
        token_expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
    )
    response = await auth_client.get("/api/social/accounts")
    assert response.json()[0]["token_expired"] is True


async def test_disconnect_removes_the_account(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    account_id = await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    response = await auth_client.delete(f"/api/social/accounts/{account_id}")
    assert response.status_code == 204
    assert (await auth_client.get("/api/social/accounts")).json() == []


async def test_disconnect_404s_for_an_unknown_account(auth_client: AsyncClient) -> None:
    response = await auth_client.delete(f"/api/social/accounts/{UNKNOWN_ID}")
    assert response.status_code == 404


async def test_activate_404s_for_an_unknown_account(auth_client: AsyncClient) -> None:
    response = await auth_client.post(f"/api/social/accounts/{UNKNOWN_ID}/activate")
    assert response.status_code == 404


async def test_activate_switches_the_destination(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    first = await connect_social_account(
        db_sessionmaker, ContentPlatform.facebook, external_id="page-1"
    )
    await connect_social_account(
        db_sessionmaker, ContentPlatform.facebook, external_id="page-2"
    )

    response = await auth_client.post(f"/api/social/accounts/{first}/activate")

    assert response.status_code == 200
    accounts = (await auth_client.get("/api/social/accounts")).json()
    active = [a["external_id"] for a in accounts if a["is_active"]]
    assert active == ["page-1"]  # exactly one destination per network


# ── preflight ──


async def test_preflight_reports_blockers_for_a_draft(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/content/generate",
        json={"topic": "First aid", "platforms": ["facebook"]},
    )
    item_id = response.json()["items"][0]["id"]

    preflight = await auth_client.get(f"/api/content/{item_id}/publish/preflight")

    assert preflight.status_code == 200
    body = preflight.json()
    assert body["ready"] is False
    assert any("Only approved posts" in b for b in body["blockers"])
    assert body["account"] is None


async def test_preflight_previews_the_exact_text_that_would_be_sent(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    body = (
        await auth_client.get(f"/api/content/{item_id}/publish/preflight")
    ).json()

    item = (await auth_client.get(f"/api/content/{item_id}")).json()
    assert body["ready"] is True
    assert body["text"].startswith(item["body"])
    assert body["char_count"] == len(body["text"])
    assert body["char_limit"] == 63_206
    assert body["image_required"] is False


async def test_preflight_flags_a_missing_instagram_image(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client, platform="instagram")
    await connect_social_account(db_sessionmaker, ContentPlatform.instagram)

    body = (
        await auth_client.get(f"/api/content/{item_id}/publish/preflight")
    ).json()

    assert body["ready"] is False
    assert body["image_required"] is True
    assert any("require an image" in b for b in body["blockers"])


async def test_preflight_404s_for_an_unknown_item(auth_client: AsyncClient) -> None:
    response = await auth_client.get(
        f"/api/content/{UNKNOWN_ID}/publish/preflight"
    )
    assert response.status_code == 404


async def test_preflight_404s_for_an_image_from_another_post(
    auth_client: AsyncClient,
) -> None:
    item_id = await _approved_item(auth_client)
    other_item_id = await _approved_item(auth_client)
    foreign_image_id = await _add_image(auth_client, other_item_id)

    response = await auth_client.get(
        f"/api/content/{item_id}/publish/preflight?image_id={foreign_image_id}"
    )

    assert response.status_code == 404
    assert "does not belong" in response.json()["detail"]


# ── publish ──


async def test_publish_returns_the_attempt_and_flips_the_status(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    response = await auth_client.post(f"/api/content/{item_id}/publish")

    assert response.status_code == 200, response.text
    publication = response.json()
    assert publication["status"] == "succeeded"
    assert publication["permalink"].startswith("https://www.facebook.com/")
    assert TEST_ACCESS_TOKEN not in response.text

    item = (await auth_client.get(f"/api/content/{item_id}")).json()
    assert item["status"] == "published"


async def test_publish_with_an_explicit_image(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client, platform="instagram")
    image_id = await _add_image(auth_client, item_id)
    await connect_social_account(db_sessionmaker, ContentPlatform.instagram)

    response = await auth_client.post(
        f"/api/content/{item_id}/publish", json={"image_id": image_id}
    )

    assert response.status_code == 200, response.text
    assert response.json()["content_image_id"] == image_id


async def test_publish_422s_on_preflight_blockers(auth_client: AsyncClient) -> None:
    item_id = await _approved_item(auth_client)  # approved, but nothing connected
    response = await auth_client.post(f"/api/content/{item_id}/publish")
    assert response.status_code == 422
    assert "Connect one in Settings" in response.json()["detail"]


async def test_publish_409s_the_second_time_and_gives_the_permalink(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    await auth_client.post(f"/api/content/{item_id}/publish")

    response = await auth_client.post(f"/api/content/{item_id}/publish")

    assert response.status_code == 409
    assert "https://www.facebook.com/" in response.json()["detail"]


async def test_publish_404s_for_an_unknown_item(auth_client: AsyncClient) -> None:
    response = await auth_client.post(f"/api/content/{UNKNOWN_ID}/publish")
    assert response.status_code == 404


async def test_publish_404s_for_an_image_from_another_post(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    other_item_id = await _approved_item(auth_client)
    foreign_image_id = await _add_image(auth_client, other_item_id)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    response = await auth_client.post(
        f"/api/content/{item_id}/publish", json={"image_id": foreign_image_id}
    )

    assert response.status_code == 404


# ── publication history ──


async def test_publications_history_lists_the_attempt(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    await auth_client.post(f"/api/content/{item_id}/publish")

    response = await auth_client.get(f"/api/content/{item_id}/publications")

    assert response.status_code == 200
    history = response.json()
    assert len(history) == 1
    assert history[0]["status"] == "succeeded"
    assert history[0]["request_summary"]["has_image"] is False


async def test_publications_history_is_empty_before_publishing(
    auth_client: AsyncClient,
) -> None:
    item_id = await _approved_item(auth_client)
    response = await auth_client.get(f"/api/content/{item_id}/publications")
    assert response.status_code == 200
    assert response.json() == []


async def test_publications_404s_for_an_unknown_item(auth_client: AsyncClient) -> None:
    response = await auth_client.get(f"/api/content/{UNKNOWN_ID}/publications")
    assert response.status_code == 404


# ── the workflow gate ──


async def test_published_items_cannot_go_back_to_draft(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    await auth_client.post(f"/api/content/{item_id}/publish")

    # A post that is live on Facebook must not be silently editable here.
    edit = await auth_client.put(
        f"/api/content/{item_id}", json={"body": "rewritten after going live"}
    )
    assert edit.status_code == 409


async def test_published_items_can_still_be_archived(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    await auth_client.post(f"/api/content/{item_id}/publish")

    response = await auth_client.post(f"/api/content/{item_id}/archive")

    assert response.status_code == 200
    assert response.json()["status"] == "archived"


async def test_published_is_filterable_in_history(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    item_id = await _approved_item(auth_client)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    await auth_client.post(f"/api/content/{item_id}/publish")

    response = await auth_client.get("/api/content?status_filter=published")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [item_id]


# ── verify ──


async def test_verify_reports_a_healthy_connection(
    auth_client: AsyncClient, db_sessionmaker
) -> None:
    account_id = await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    response = await auth_client.post(f"/api/social/accounts/{account_id}/verify")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["error"] is None
    assert body["account"]["display_name"] == "Western Riverina Community College"
    assert TEST_ACCESS_TOKEN not in response.text


async def test_verify_404s_for_an_unknown_account(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        f"/api/social/accounts/{UNKNOWN_ID}/verify"
    )
    assert response.status_code == 404


async def test_verify_requires_auth(client: AsyncClient) -> None:
    response = await client.post(f"/api/social/accounts/{UNKNOWN_ID}/verify")
    assert response.status_code == 401


async def test_verify_returns_200_with_ok_false_when_the_token_is_dead(
    auth_client: AsyncClient, db_sessionmaker, app
) -> None:
    # A dead token is information, not a request error — same contract as
    # publish: the check ran, and this is what it found.
    import app.api.publishing as publishing_api
    from app.publishing.publishers.base import PublishError

    account_id = await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    class DeadTokenVerifier:
        async def verify(self, account):
            raise PublishError("Session expired.", code="reauth")

    original = publishing_api.get_verifier
    publishing_api.get_verifier = lambda platform, settings, **kw: DeadTokenVerifier()  # type: ignore[assignment]
    try:
        response = await auth_client.post(f"/api/social/accounts/{account_id}/verify")
    finally:
        publishing_api.get_verifier = original  # type: ignore[assignment]

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["error_code"] == "reauth"
    assert "Session expired" in body["error"]
