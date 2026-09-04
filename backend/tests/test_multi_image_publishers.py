"""Multi-image publishing, per network, asserted on the wire payloads.

Every platform models several images as a *different shape* from one, not as a
list of length one, so each publisher has two paths and both have to be pinned
down. The single-image assertions live in ``test_live_publishers.py`` and must
keep passing unchanged — that is the point: adding carousels must not move the
posts that already work.

The property this file exists to protect is the retry boundary. Scaffolding —
unpublished Facebook photos, Instagram child containers, uploaded LinkedIn
assets — is private, invisible, and freely repeatable. The single call that
creates the post is not, and no amount of throttling may cause it to run twice.
"""

from __future__ import annotations

import json

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
from app.publishing.publishers.linkedin import LinkedInPublisher
from tests.conftest import make_settings

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def _settings(**overrides):
    defaults = {
        "publish_retry_base_delay_seconds": 0.0,
        "instagram_container_poll_delay_seconds": 0.0,
    }
    return make_settings(**{**defaults, **overrides})


def _images(count: int, *, with_url: bool = False) -> tuple[PublishImage, ...]:
    """`count` distinguishable images, so order is assertable."""
    return tuple(
        PublishImage(
            data=JPEG + bytes([index]),
            url=f"https://api.test/img-{index + 1}.jpg" if with_url else None,
            alt=f"image {index + 1}",
        )
        for index in range(count)
    )


def _request(
    platform: ContentPlatform,
    images: tuple[PublishImage, ...],
    *,
    external_id: str = "page-1",
    metadata: dict | None = None,
) -> PublishRequest:
    return PublishRequest(
        text="Enrol in First Aid.",
        account=ResolvedAccount(
            id="acct-1",
            platform=platform,
            external_id=external_id,
            display_name="WRCC",
            access_token="PAGE-TOKEN",
            metadata=metadata or {},
        ),
        images=images,
    )


# ── Facebook ──


def _facebook_transport(feed_response: httpx.Response | None = None):
    calls: list[tuple[str, str]] = []
    photos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode(errors="replace")
        calls.append((request.url.path, body))
        if request.url.path.endswith("/photos"):
            photos["n"] += 1
            return httpx.Response(200, json={"id": f"photo-{photos['n']}"})
        return feed_response or httpx.Response(200, json={"id": "page-1_story"})

    return httpx.MockTransport(handler), calls


async def test_facebook_uploads_each_photo_unpublished_then_makes_one_story() -> None:
    transport, calls = _facebook_transport()

    result = await FacebookPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.facebook, _images(3))
    )

    paths = [path for path, _ in calls]
    assert paths == [
        "/v23.0/page-1/photos",
        "/v23.0/page-1/photos",
        "/v23.0/page-1/photos",
        "/v23.0/page-1/feed",
    ]
    # Each photo is staged, not posted — three visible photos would be three
    # posts on the Page instead of one.
    assert all("published" in body for path, body in calls if path.endswith("/photos"))
    assert result.external_post_id == "page-1_story"


async def test_facebook_attaches_the_photos_in_order() -> None:
    transport, calls = _facebook_transport()

    await FacebookPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.facebook, _images(3))
    )

    _, feed_body = calls[-1]
    # Graph reads indexed form fields, not a JSON array, and the index is the
    # order the reader will scroll.
    for position in range(3):
        assert (
            f"attached_media%5B{position}%5D=" in feed_body
            or f"attached_media[{position}]=" in feed_body
        )
    assert "photo-1" in feed_body
    assert "photo-3" in feed_body


async def test_facebook_keeps_the_single_photo_path_for_one_image() -> None:
    # One image must still take the old route: same endpoint, same caption
    # handling, same permalink shape.
    transport, calls = _facebook_transport()

    await FacebookPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.facebook, _images(1))
    )

    assert [path for path, _ in calls] == ["/v23.0/page-1/photos"]
    assert "caption" in calls[0][1]


async def test_facebook_creates_the_story_exactly_once_when_throttled() -> None:
    # The uploads may be retried freely; the feed call may not. A second feed
    # call is a second post on the Page.
    feed_calls = {"n": 0}
    photo_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/photos"):
            photo_calls["n"] += 1
            if photo_calls["n"] == 1:
                return httpx.Response(
                    500, json={"error": {"message": "temporary", "code": 2}}
                )
            return httpx.Response(200, json={"id": f"photo-{photo_calls['n']}"})
        feed_calls["n"] += 1
        return httpx.Response(200, json={"id": "page-1_story"})

    await FacebookPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(_request(ContentPlatform.facebook, _images(2)))

    assert photo_calls["n"] > 2  # the batch was retried
    assert feed_calls["n"] == 1


async def test_facebook_multi_photo_without_an_id_is_ambiguous() -> None:
    transport, _ = _facebook_transport(feed_response=httpx.Response(200, json={}))

    with pytest.raises(PublishError) as excinfo:
        await FacebookPublisher(_settings(), transport=transport).publish(
            _request(ContentPlatform.facebook, _images(2))
        )

    # Probably live and unnameable: never retried, and the message says to look.
    assert excinfo.value.code == "ambiguous"
    assert "Check the Page" in str(excinfo.value)


# ── Instagram ──


def _instagram_transport():
    calls: list[tuple[str, str]] = []
    containers = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = request.content.decode(errors="replace")
        calls.append((path, body))
        if path.endswith("/media"):
            containers["n"] += 1
            return httpx.Response(200, json={"id": f"container-{containers['n']}"})
        if path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "media-9"})
        if "permalink" in request.url.query.decode():
            return httpx.Response(200, json={"permalink": "https://instagram.test/p/1"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    return httpx.MockTransport(handler), calls


async def test_instagram_builds_a_child_per_image_then_one_carousel_parent() -> None:
    transport, calls = _instagram_transport()

    result = await InstagramPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.instagram, _images(3, with_url=True), external_id="ig-1")
    )

    media_calls = [body for path, body in calls if path.endswith("/media")]
    assert len(media_calls) == 4  # three children plus the parent
    assert all("is_carousel_item" in body for body in media_calls[:3])
    parent = media_calls[3]
    assert "CAROUSEL" in parent
    assert "container-1%2Ccontainer-2%2Ccontainer-3" in parent or (
        "container-1,container-2,container-3" in parent
    )
    assert result.external_post_id == "media-9"


async def test_instagram_puts_the_caption_on_the_parent_only() -> None:
    # A caption on a child is ignored by Instagram; sending it there and not on
    # the parent would publish a carousel with no text at all.
    transport, calls = _instagram_transport()

    await InstagramPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.instagram, _images(2, with_url=True), external_id="ig-1")
    )

    media_calls = [body for path, body in calls if path.endswith("/media")]
    assert all("caption" not in body for body in media_calls[:2])
    assert "caption" in media_calls[2]


async def test_instagram_keeps_the_single_container_path_for_one_image() -> None:
    transport, calls = _instagram_transport()

    await InstagramPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.instagram, _images(1, with_url=True), external_id="ig-1")
    )

    media_calls = [body for path, body in calls if path.endswith("/media")]
    assert len(media_calls) == 1
    assert "is_carousel_item" not in media_calls[0]
    assert "caption" in media_calls[0]


async def test_instagram_publishes_the_carousel_exactly_once_when_throttled() -> None:
    # Containers are scaffolding and may be rebuilt; media_publish creates the
    # post and must run once no matter how often the containers are retried.
    container_calls = {"n": 0}
    publish_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/media"):
            container_calls["n"] += 1
            if container_calls["n"] == 2:
                return httpx.Response(
                    429, json={"error": {"message": "rate limited", "code": 4}}
                )
            return httpx.Response(200, json={"id": f"container-{container_calls['n']}"})
        if path.endswith("/media_publish"):
            publish_calls["n"] += 1
            return httpx.Response(200, json={"id": "media-9"})
        if "permalink" in request.url.query.decode():
            return httpx.Response(200, json={"permalink": "https://instagram.test/p/1"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    await InstagramPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(
        _request(ContentPlatform.instagram, _images(2, with_url=True), external_id="ig-1")
    )

    assert container_calls["n"] > 3  # the whole carousel build was retried
    assert publish_calls["n"] == 1


async def test_instagram_refuses_a_carousel_it_cannot_serve_publicly() -> None:
    # Instagram fetches every child itself, so one unsigned image is enough to
    # make the whole carousel impossible.
    images = _images(2, with_url=True)
    partial = (images[0], PublishImage(data=JPEG, url=None, alt="no url"))
    transport, _ = _instagram_transport()

    with pytest.raises(PublishError) as excinfo:
        await InstagramPublisher(_settings(), transport=transport).publish(
            _request(ContentPlatform.instagram, partial, external_id="ig-1")
        )

    assert excinfo.value.code == "unreachable_media"


# ── LinkedIn ──


def _linkedin_transport():
    posts: list[dict] = []
    uploads = {"n": 0}
    put_bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in request.url.query.decode():
            uploads["n"] += 1
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": f"https://upload.linkedin.test/put-{uploads['n']}",
                        "image": f"urn:li:image:{uploads['n']}",
                    }
                },
            )
        if request.method == "PUT":
            put_bodies.append(request.content)
            return httpx.Response(201)
        posts.append(json.loads(request.content))
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"})

    return httpx.MockTransport(handler), posts, put_bodies


async def test_linkedin_several_images_become_a_multi_image_post() -> None:
    transport, posts, put_bodies = _linkedin_transport()

    await LinkedInPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.linkedin, _images(3), external_id="777")
    )

    content = posts[0]["content"]
    assert "media" not in content  # the singular shape is not a list of one
    images = content["multiImage"]["images"]
    assert [entry["id"] for entry in images] == [
        "urn:li:image:1",
        "urn:li:image:2",
        "urn:li:image:3",
    ]
    assert [entry["altText"] for entry in images] == [
        "image 1",
        "image 2",
        "image 3",
    ]
    assert len(put_bodies) == 3


async def test_linkedin_uploads_each_image_in_selection_order() -> None:
    transport, _, put_bodies = _linkedin_transport()

    await LinkedInPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.linkedin, _images(3), external_id="777")
    )

    assert put_bodies == [JPEG + bytes([0]), JPEG + bytes([1]), JPEG + bytes([2])]


async def test_linkedin_keeps_the_single_media_shape_for_one_image() -> None:
    transport, posts, _ = _linkedin_transport()

    await LinkedInPublisher(_settings(), transport=transport).publish(
        _request(ContentPlatform.linkedin, _images(1), external_id="777")
    )

    assert posts[0]["content"]["media"]["id"] == "urn:li:image:1"
    assert "multiImage" not in posts[0]["content"]


async def test_linkedin_retries_one_upload_without_re_uploading_the_rest() -> None:
    # Re-uploading four images because the fifth was throttled is waste, not
    # safety: each asset is a private URN, retried on its own.
    attempts: list[int] = []
    uploads = {"n": 0}
    failed_once = {"done": False}
    posts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "initializeUpload" in request.url.query.decode():
            uploads["n"] += 1
            attempts.append(uploads["n"])
            return httpx.Response(
                200,
                json={
                    "value": {
                        "uploadUrl": "https://upload.linkedin.test/put",
                        "image": f"urn:li:image:{uploads['n']}",
                    }
                },
            )
        if request.method == "PUT":
            if not failed_once["done"]:
                failed_once["done"] = True
                return httpx.Response(503)
            return httpx.Response(201)
        posts.append(json.loads(request.content))
        return httpx.Response(201, headers={"x-restli-id": "urn:li:share:9"})

    await LinkedInPublisher(
        _settings(), transport=httpx.MockTransport(handler)
    ).publish(_request(ContentPlatform.linkedin, _images(2), external_id="777"))

    # Three initializations for two images: one retry, not a restart of both.
    assert uploads["n"] == 3
    assert len(posts) == 1
