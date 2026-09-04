"""Live Facebook / Instagram / LinkedIn publishers, over scripted transports.

These assert the exact wire contract each network requires — the endpoints, the
field names, the ordering, and where the post id comes back from. Getting any
of those subtly wrong produces either a rejected request or, worse, a published
post we cannot link to.
"""

from __future__ import annotations

import httpx
import pytest

from app.db.enums import ContentPlatform
from app.publishing.publishers.base import (
    PublishError,
    PublishImage,
    PublishRequest,
    ResolvedAccount,
)
from app.publishing.publishers.facebook import FacebookPublisher
from app.publishing.publishers.instagram import InstagramPublisher
from app.publishing.publishers.linkedin import (
    LinkedInPublisher,
    escape_commentary,
    permalink_for,
)
from tests.conftest import make_settings

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _settings(**overrides):
    # No sleeping in the suite: retries and container polls run at zero delay.
    defaults = {
        "publish_mock": False,
        "meta_app_id": "app",
        "meta_app_secret": "secret",
        "linkedin_client_id": "li",
        "linkedin_client_secret": "li-secret",
        "publish_retry_base_delay_seconds": 0.0,
        "instagram_container_poll_delay_seconds": 0.0,
    }
    return make_settings(**{**defaults, **overrides})


def _request(
    platform: ContentPlatform,
    *,
    text: str = "Enrol in First Aid.",
    image_url: str | None = None,
    image_bytes: bytes | None = None,
    images: tuple[PublishImage, ...] | None = None,
    link: str | None = None,
    metadata: dict | None = None,
    external_id: str = "page-1",
) -> PublishRequest:
    """Build a request. `image_url`/`image_bytes` build the single-image case;
    `images` is for the multi-image ones."""
    if images is None:
        images = (
            (
                PublishImage(
                    data=image_bytes or b"",
                    url=image_url,
                    alt="a bright classroom",
                ),
            )
            if (image_url or image_bytes)
            else ()
        )
    return PublishRequest(
        text=text,
        account=ResolvedAccount(
            id="acct-1",
            platform=platform,
            external_id=external_id,
            display_name="WRCC",
            access_token="PAGE-TOKEN",
            metadata=metadata or {},
        ),
        images=images,
        link=link,
    )


def _images(count: int, *, with_url: bool = False) -> tuple[PublishImage, ...]:
    """`count` distinguishable images, so a test can assert on their order."""
    return tuple(
        PublishImage(
            data=JPEG + bytes([index]),
            url=f"https://api.test/img-{index + 1}.jpg" if with_url else None,
            alt=f"image {index + 1}",
        )
        for index in range(count)
    )


# ── Facebook ──


async def test_facebook_text_post_goes_to_the_feed() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.content.decode()))
        return httpx.Response(200, json={"id": "page-1_99"})

    result = await FacebookPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(_request(ContentPlatform.facebook))

    path, body = seen[0]
    assert path.endswith("/page-1/feed")
    assert "message=Enrol" in body
    assert result.external_post_id == "page-1_99"
    assert result.permalink == "https://www.facebook.com/page-1_99"


async def test_facebook_includes_the_reference_link() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.content.decode())
        return httpx.Response(200, json={"id": "p_1"})

    await FacebookPublisher(_settings(), transport=httpx.MockTransport(handler)).publish(
        _request(ContentPlatform.facebook, link="https://wrcc.nsw.edu.au/first-aid")
    )

    assert "link=https" in seen[0]


async def test_facebook_photo_post_uploads_bytes_not_a_url() -> None:
    # Uploading bytes is why Facebook publishing works without a public host.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "photo-1", "post_id": "page-1_77"})

    result = await FacebookPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(_request(ContentPlatform.facebook, image_bytes=JPEG))

    request = seen[0]
    assert request.url.path.endswith("/page-1/photos")
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert JPEG in request.content
    # The story id, not the photo id — that is what a permalink must point at.
    assert result.external_post_id == "page-1_77"


async def test_facebook_photo_falls_back_to_the_photo_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "photo-only"})

    result = await FacebookPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(_request(ContentPlatform.facebook, image_bytes=JPEG))

    assert result.external_post_id == "photo-only"


async def test_facebook_expired_token_asks_for_a_reconnect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": 190, "message": "Token expired."}}
        )

    with pytest.raises(PublishError) as excinfo:
        await FacebookPublisher(
            _settings(), transport=httpx.MockTransport(handler)
        ).publish(_request(ContentPlatform.facebook))

    assert excinfo.value.code == "reauth"
    assert "Reconnect the account" in str(excinfo.value)


async def test_facebook_retries_a_throttled_call_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(
                400, json={"error": {"code": 4, "message": "Rate limit."}}
            )
        return httpx.Response(200, json={"id": "p_ok"})

    result = await FacebookPublisher(
        _settings(publish_max_attempts=3), transport=httpx.MockTransport(handler)
    ).publish(_request(ContentPlatform.facebook))

    assert calls["n"] == 3
    assert result.external_post_id == "p_ok"


async def test_facebook_gives_up_after_the_attempt_budget() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"code": 4, "message": "Rate."}})

    with pytest.raises(PublishError) as excinfo:
        await FacebookPublisher(
            _settings(publish_max_attempts=2), transport=httpx.MockTransport(handler)
        ).publish(_request(ContentPlatform.facebook))

    assert calls["n"] == 2
    assert excinfo.value.code == "rate_limited"


async def test_an_auth_failure_is_not_retried() -> None:
    # Retrying a dead token just burns quota and delays the real message.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": {"code": 190, "message": "Dead."}})

    with pytest.raises(PublishError):
        await FacebookPublisher(
            _settings(publish_max_attempts=3), transport=httpx.MockTransport(handler)
        ).publish(_request(ContentPlatform.facebook))

    assert calls["n"] == 1


async def test_facebook_success_without_an_id_is_not_treated_as_published() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(PublishError, match="returned no id"):
        await FacebookPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(_request(ContentPlatform.facebook))


# ── Instagram ──


def _instagram_transport(*, statuses: list[str | None] | None = None, permalink="https://instagram.test/p/1"):
    seen: list[str] = []
    polls = {"n": 0}
    states = statuses if statuses is not None else ["FINISHED"]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(f"{request.method} {path}")
        if path.endswith("/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "media-9"})
        if "permalink" in request.url.query.decode():
            return httpx.Response(200, json={"permalink": permalink})
        state = states[min(polls["n"], len(states) - 1)]
        polls["n"] += 1
        return httpx.Response(200, json={"status_code": state} if state else {})

    return httpx.MockTransport(handler), seen


async def test_instagram_creates_a_container_then_publishes_it() -> None:
    transport, seen = _instagram_transport()

    result = await InstagramPublisher(_settings(), transport=transport).publish(
        _request(
            ContentPlatform.instagram,
            external_id="ig-1",
            image_url="https://api.test/img.jpg",
        )
    )

    assert seen[0] == "POST /v23.0/ig-1/media"
    assert "media_publish" in seen[2]
    assert result.external_post_id == "media-9"
    assert result.permalink == "https://instagram.test/p/1"


async def test_instagram_waits_for_the_container_to_finish() -> None:
    transport, seen = _instagram_transport(
        statuses=["IN_PROGRESS", "IN_PROGRESS", "FINISHED"]
    )

    await InstagramPublisher(_settings(), transport=transport).publish(
        _request(
            ContentPlatform.instagram,
            external_id="ig-1",
            image_url="https://api.test/img.jpg",
        )
    )

    polls = [entry for entry in seen if entry.startswith("GET /v23.0/container-1")]
    assert len(polls) == 3


async def test_instagram_reports_a_container_that_errored() -> None:
    transport, _ = _instagram_transport(statuses=["ERROR"])

    with pytest.raises(PublishError) as excinfo:
        await InstagramPublisher(
            _settings(publish_max_attempts=1), transport=transport
        ).publish(
            _request(
                ContentPlatform.instagram,
                external_id="ig-1",
                image_url="https://api.test/img.jpg",
            )
        )

    assert excinfo.value.code == "invalid"
    assert "size and ratio" in str(excinfo.value)


async def test_instagram_gives_up_on_a_container_that_never_finishes() -> None:
    transport, _ = _instagram_transport(statuses=["IN_PROGRESS"])

    with pytest.raises(PublishError, match="did not finish processing"):
        await InstagramPublisher(
            _settings(publish_max_attempts=1, instagram_container_poll_attempts=3),
            transport=transport,
        ).publish(
            _request(
                ContentPlatform.instagram,
                external_id="ig-1",
                image_url="https://api.test/img.jpg",
            )
        )


async def test_instagram_treats_a_missing_status_as_ready() -> None:
    # Image containers are usually complete on creation and some responses omit
    # the field; polling it out would fail a post that was fine.
    transport, _ = _instagram_transport(statuses=[None])

    result = await InstagramPublisher(_settings(), transport=transport).publish(
        _request(
            ContentPlatform.instagram,
            external_id="ig-1",
            image_url="https://api.test/img.jpg",
        )
    )

    assert result.external_post_id == "media-9"


async def test_instagram_without_a_public_url_says_exactly_what_is_missing() -> None:
    with pytest.raises(PublishError) as excinfo:
        await InstagramPublisher(_settings()).publish(
            _request(ContentPlatform.instagram, external_id="ig-1", image_bytes=JPEG)
        )

    assert excinfo.value.code == "unreachable_media"
    assert "PUBLIC_API_BASE_URL" in str(excinfo.value)


async def test_instagram_keeps_the_post_when_the_permalink_lookup_fails() -> None:
    # The post is already live by then; losing the link must not fail the publish.
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/media"):
            return httpx.Response(200, json={"id": "c1"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "media-9"})
        if "permalink" in request.url.query.decode():
            return httpx.Response(400, json={"error": {"code": 100, "message": "no"}})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    result = await InstagramPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(
        _request(
            ContentPlatform.instagram,
            external_id="ig-1",
            image_url="https://api.test/img.jpg",
        )
    )

    assert result.external_post_id == "media-9"
    assert result.permalink is None


# ── LinkedIn ──


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Enrol (now)", "Enrol \\(now\\)"),
        ("#FirstAid", "\\#FirstAid"),
        ("a|b{c}", "a\\|b\\{c\\}"),
        ("under_score *star*", "under\\_score \\*star\\*"),
        ("back\\slash", "back\\\\slash"),
        ("plain text 123", "plain text 123"),
    ],
)
def test_commentary_escaping(raw: str, expected: str) -> None:
    # LinkedIn rejects unescaped reserved characters, and generated posts are
    # full of '(', ')' and '#'.
    assert escape_commentary(raw) == expected


async def test_linkedin_text_post_uses_the_organization_author() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:123"})

    result = await LinkedInPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(
        _request(
            ContentPlatform.linkedin,
            external_id="777",
            metadata={"author_urn": "urn:li:organization:777"},
        )
    )

    body = seen[0]
    assert body["author"] == "urn:li:organization:777"
    assert body["lifecycleState"] == "PUBLISHED"
    assert body["visibility"] == "PUBLIC"
    assert body["distribution"]["feedDistribution"] == "MAIN_FEED"
    # The id comes back in a header, not the body.
    assert result.external_post_id == "urn:li:share:123"
    assert result.permalink == permalink_for("urn:li:share:123")


async def test_linkedin_falls_back_to_an_organization_urn_from_the_id() -> None:
    import json

    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})

    await LinkedInPublisher(_settings(), transport=httpx.MockTransport(handler)).publish(
        _request(ContentPlatform.linkedin, external_id="555")
    )

    assert seen[0]["author"] == "urn:li:organization:555"


async def test_linkedin_image_post_initializes_uploads_then_references_the_urn() -> None:

    seen: list[str] = []
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        if "initializeUpload" in request.url.query.decode():
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.linkedin.test/put",
                        "image": "urn:li:image:abc",
                    }
                },
            )
        if request.method == "PUT":
            bodies.append(request.content)
            return httpx.Response(201)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"})

    await LinkedInPublisher(_settings(), transport=httpx.MockTransport(handler)).publish(
        _request(
            ContentPlatform.linkedin,
            external_id="777",
            image_bytes=JPEG,
            metadata={"author_urn": "urn:li:organization:777"},
        )
    )

    assert seen[0] == "POST /rest/images"
    assert seen[1] == "PUT /put"
    assert seen[2] == "POST /rest/posts"
    assert bodies == [JPEG]


async def test_linkedin_image_post_carries_alt_text() -> None:
    import json

    posts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in request.url.query.decode():
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.linkedin.test/put",
                        "image": "urn:li:image:abc",
                    }
                },
            )
        if request.method == "PUT":
            return httpx.Response(201)
        posts.append(json.loads(request.content))
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"})

    await LinkedInPublisher(_settings(), transport=httpx.MockTransport(handler)).publish(
        _request(ContentPlatform.linkedin, external_id="7", image_bytes=JPEG)
    )

    media = posts[0]["content"]["media"]
    assert media["id"] == "urn:li:image:abc"
    assert media["altText"] == "a bright classroom"


async def test_linkedin_sends_the_versioning_headers() -> None:
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:1"})

    await LinkedInPublisher(
        _settings(linkedin_api_version="202506"),
        transport=httpx.MockTransport(handler),
    ).publish(_request(ContentPlatform.linkedin, external_id="1"))

    assert seen[0]["LinkedIn-Version"] == "202506"
    assert seen[0]["X-Restli-Protocol-Version"] == "2.0.0"
    assert seen[0]["Authorization"] == "Bearer PAGE-TOKEN"


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [(401, "reauth"), (403, "reauth"), (429, "rate_limited"), (500, "transient"), (400, "invalid")],
)
async def test_linkedin_http_status_maps_to_an_error_code(
    status_code: int, expected_code: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "nope"})

    with pytest.raises(PublishError) as excinfo:
        await LinkedInPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(_request(ContentPlatform.linkedin, external_id="1"))

    assert excinfo.value.code == expected_code


async def test_linkedin_post_without_an_id_header_is_not_a_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201)

    with pytest.raises(PublishError, match="returned no id"):
        await LinkedInPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(_request(ContentPlatform.linkedin, external_id="1"))


async def test_linkedin_upload_initialization_failure_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in request.url.query.decode():
            return httpx.Response(400, json={"message": "bad owner"})
        return httpx.Response(201, headers={"x-restli-id": "x"})

    with pytest.raises(PublishError, match="start the image upload"):
        await LinkedInPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(
            _request(ContentPlatform.linkedin, external_id="1", image_bytes=JPEG)
        )


async def test_linkedin_upload_without_a_target_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in request.url.query.decode():
            return httpx.Response(200, json={"value": {}})
        return httpx.Response(201, headers={"x-restli-id": "x"})

    with pytest.raises(PublishError, match="upload target"):
        await LinkedInPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(
            _request(ContentPlatform.linkedin, external_id="1", image_bytes=JPEG)
        )


async def test_linkedin_byte_upload_failure_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in request.url.query.decode():
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.linkedin.test/put",
                        "image": "urn:li:image:abc",
                    }
                },
            )
        if request.method == "PUT":
            return httpx.Response(500)
        return httpx.Response(201, headers={"x-restli-id": "x"})

    with pytest.raises(PublishError, match="upload the image"):
        await LinkedInPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(
            _request(ContentPlatform.linkedin, external_id="1", image_bytes=JPEG)
        )


async def test_linkedin_unreadable_upload_response_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in request.url.query.decode():
            return httpx.Response(200, text="<html>not json</html>")
        return httpx.Response(201, headers={"x-restli-id": "x"})

    with pytest.raises(PublishError) as excinfo:
        await LinkedInPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(
            _request(ContentPlatform.linkedin, external_id="1", image_bytes=JPEG)
        )

    assert excinfo.value.code == "transient"


# ── remaining error mappings ──


async def test_facebook_transient_graph_code_is_retryable() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            # Code 2 is Graph's "API Service" temporary failure.
            return httpx.Response(
                500, json={"error": {"code": 2, "message": "Temporary."}}
            )
        return httpx.Response(200, json={"id": "p_ok"})

    result = await FacebookPublisher(
        _settings(publish_max_attempts=2), transport=httpx.MockTransport(handler)
    ).publish(_request(ContentPlatform.facebook))

    assert calls["n"] == 2
    assert result.external_post_id == "p_ok"


async def test_instagram_missing_container_id_is_transient() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(PublishError, match="media container id"):
        await InstagramPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(
            _request(
                ContentPlatform.instagram,
                external_id="ig-1",
                image_url="https://api.test/i.jpg",
            )
        )


async def test_instagram_missing_media_id_is_not_treated_as_published() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/media"):
            return httpx.Response(200, json={"id": "c1"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    with pytest.raises(PublishError, match="returned no media id"):
        await InstagramPublisher(
            _settings(publish_max_attempts=1), transport=httpx.MockTransport(handler)
        ).publish(
            _request(
                ContentPlatform.instagram,
                external_id="ig-1",
                image_url="https://api.test/i.jpg",
            )
        )


# ── the double-post guard ──
#
# Every test below pins `publish_max_attempts` **above 1** on purpose. The
# retry path is the only place a duplicate post can come from, so a test that
# pins it to 1 proves nothing about it — that is precisely how the original bug
# shipped green. Each of these fails on the pre-fix code by posting 2–3 times.


async def test_facebook_does_not_retry_a_post_it_could_not_name() -> None:
    """A 200 with no id means Graph took the post. Retrying would post it twice."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    with pytest.raises(PublishError) as excinfo:
        await FacebookPublisher(
            _settings(publish_max_attempts=3), transport=httpx.MockTransport(handler)
        ).publish(_request(ContentPlatform.facebook))

    assert excinfo.value.code == "ambiguous"
    assert len(calls) == 1
    # The operator has to be told to go and look, because we cannot.
    assert "Check the Page" in str(excinfo.value)


async def test_instagram_does_not_republish_a_post_it_could_not_name() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path.endswith("/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={})  # accepted, but unnamed
        return httpx.Response(200, json={"status_code": "FINISHED"})

    with pytest.raises(PublishError) as excinfo:
        await InstagramPublisher(
            _settings(publish_max_attempts=3), transport=httpx.MockTransport(handler)
        ).publish(
            _request(
                ContentPlatform.instagram,
                external_id="ig-1",
                image_url="https://api.test/i.jpg",
            )
        )

    assert excinfo.value.code == "ambiguous"
    assert sum(1 for path in seen if path.endswith("/media_publish")) == 1
    # Nor was the whole sequence replayed from the top.
    assert sum(1 for path in seen if path.endswith("/media")) == 1


async def test_instagram_publishes_the_container_exactly_once_even_when_throttled() -> None:
    """The publish step is outside the retry, so *nothing* re-runs it.

    A throttled call almost certainly created nothing, so this costs a retry we
    could technically have afforded. That is the trade the feature makes: for
    the one irreversible action in the app, "press it again yourself" beats a
    rule about which provider codes truly prove a rejection.
    """
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(path)
        if path.endswith("/media"):
            return httpx.Response(200, json={"id": "container-1"})
        if path.endswith("/media_publish"):
            return httpx.Response(
                400, json={"error": {"code": 4, "message": "Rate limited."}}
            )
        return httpx.Response(200, json={"status_code": "FINISHED"})

    with pytest.raises(PublishError) as excinfo:
        await InstagramPublisher(
            _settings(publish_max_attempts=3), transport=httpx.MockTransport(handler)
        ).publish(
            _request(
                ContentPlatform.instagram,
                external_id="ig-1",
                image_url="https://api.test/i.jpg",
            )
        )

    assert excinfo.value.code == "rate_limited"
    assert sum(1 for path in seen if path.endswith("/media_publish")) == 1


async def test_linkedin_does_not_repost_when_the_id_header_is_missing() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "initializeUpload" in url:
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.test/1",
                        "image": "urn:li:image:1",
                    }
                },
            )
        if "upload.test" in url:
            return httpx.Response(201)
        return httpx.Response(201)  # created, but no x-restli-id

    with pytest.raises(PublishError) as excinfo:
        await LinkedInPublisher(
            _settings(publish_max_attempts=3), transport=httpx.MockTransport(handler)
        ).publish(
            _request(
                ContentPlatform.linkedin,
                image_bytes=JPEG,
                metadata={"author_urn": "urn:li:organization:5"},
            )
        )

    assert excinfo.value.code == "ambiguous"
    assert sum(1 for url in seen if url.endswith("/rest/posts")) == 1
    assert sum(1 for url in seen if "initializeUpload" in url) == 1


async def test_linkedin_retries_the_image_upload_but_still_posts_once() -> None:
    """The upload *is* retried: a second copy of an image is on nobody's feed."""
    seen: list[str] = []
    initializations = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if "initializeUpload" in url:
            initializations["n"] += 1
            if initializations["n"] == 1:
                return httpx.Response(503, json={"message": "Upstream hiccup."})
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.test/1",
                        "image": "urn:li:image:1",
                    }
                },
            )
        if "upload.test" in url:
            return httpx.Response(201)
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"})

    result = await LinkedInPublisher(
        _settings(publish_max_attempts=3), transport=httpx.MockTransport(handler)
    ).publish(
        _request(
            ContentPlatform.linkedin,
            image_bytes=JPEG,
            metadata={"author_urn": "urn:li:organization:5"},
        )
    )

    assert result.external_post_id == "urn:li:share:9"
    assert initializations["n"] == 2
    assert sum(1 for url in seen if url.endswith("/rest/posts")) == 1


# ── verify ──


async def test_facebook_verify_passes_on_a_live_token() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"id": "page-1", "name": "WRCC"})

    account = _request(ContentPlatform.facebook).account
    await FacebookPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).verify(account)

    assert seen[0].endswith("/page-1")


async def test_facebook_verify_reports_a_dead_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": 190, "message": "Session expired."}}
        )

    with pytest.raises(PublishError) as excinfo:
        await FacebookPublisher(
            _settings(), transport=httpx.MockTransport(handler)
        ).verify(_request(ContentPlatform.facebook).account)

    assert excinfo.value.code == "reauth"


async def test_instagram_verify_uses_the_username_field() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.query.decode())
        return httpx.Response(200, json={"id": "ig-1", "username": "wrcc"})

    await InstagramPublisher(_settings(), transport=httpx.MockTransport(handler)).verify(
        _request(ContentPlatform.instagram, external_id="ig-1").account
    )

    assert "username" in seen[0]


async def test_linkedin_verify_probes_org_acls_for_a_company_page() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"elements": []})

    await LinkedInPublisher(_settings(), transport=httpx.MockTransport(handler)).verify(
        _request(
            ContentPlatform.linkedin,
            metadata={"author_urn": "urn:li:organization:1"},
        ).account
    )

    assert seen[0] == "/rest/organizationAcls"


async def test_linkedin_verify_probes_userinfo_in_member_mode() -> None:
    # An org app has no profile scope and a member app has no org scope —
    # probing the wrong endpoint would report a healthy token as broken.
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={"name": "Julian"})

    await LinkedInPublisher(_settings(), transport=httpx.MockTransport(handler)).verify(
        _request(
            ContentPlatform.linkedin, metadata={"author_urn": "urn:li:person:xyz"}
        ).account
    )

    assert seen[0] == "/v2/userinfo"


async def test_linkedin_verify_reports_revoked_credentials() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Invalid token."})

    with pytest.raises(PublishError) as excinfo:
        await LinkedInPublisher(
            _settings(), transport=httpx.MockTransport(handler)
        ).verify(_request(ContentPlatform.linkedin).account)

    assert excinfo.value.code == "reauth"
