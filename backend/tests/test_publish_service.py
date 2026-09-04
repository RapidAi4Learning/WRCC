"""PublishService: the gates, the attempt record, and what survives a failure."""

from __future__ import annotations

import datetime as dt
import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import select

from app.db.enums import ContentPlatform, ContentStatus, PublishStatus
from app.db.models import (
    AuditLog,
    ContentItem,
    ContentItemMedia,
    ContentPublication,
    MediaAsset,
)
from app.publishing.publishers.base import PublishError, PublishResult
from app.publishing.service import (
    AlreadyPublishedError,
    ImageNotFoundError,
    PublishNotAllowedError,
    PublishService,
)
from tests.conftest import TEST_ACCESS_TOKEN, connect_social_account, make_settings

JPEG_MAGIC = b"\xff\xd8\xff"


def make_png(width: int = 1024, height: int = 1024) -> bytes:
    """A real PNG: the service converts stored bytes before publishing, so a
    fake header is no longer enough to stand in for an image."""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (20, 92, 63)).save(buffer, format="PNG")
    return buffer.getvalue()


PNG = make_png()


class RecordingPublisher:
    """Captures what it was asked to send, then reports success."""

    def __init__(self) -> None:
        self.requests: list = []

    async def publish(self, request):
        self.requests.append(request)
        return PublishResult(
            external_post_id="page_abc123",
            permalink="https://www.facebook.com/page_abc123",
        )


class FailingPublisher:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def publish(self, request):
        raise self._error


async def _make_item(
    db_sessionmaker,
    *,
    platform: ContentPlatform = ContentPlatform.facebook,
    status: ContentStatus = ContentStatus.approved,
    with_image: bool = False,
    hashtags: list[str] | None = None,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    async with db_sessionmaker() as session:
        item = ContentItem(
            platform=platform,
            topic="First aid",
            variant_style="direct",
            generated_body="Enrol in our First Aid course this spring.",
            hashtags=hashtags if hashtags is not None else ["#firstaid"],
            call_to_action="Enrol today.",
            status=status,
        )
        session.add(item)
        await session.flush()
        image_id = None
        if with_image:
            image = MediaAsset(
                generation_group=item.generation_group,
                prompt="a bright classroom",
                model="mock",
                data=PNG,
            )
            session.add(image)
            await session.flush()
            # An attached image, not merely an existing one: publishing sends
            # the item's selection, and "there is a picture in the library"
            # is deliberately no longer the same statement.
            session.add(
                ContentItemMedia(
                    content_item_id=item.id, media_asset_id=image.id, position=0
                )
            )
            image_id = image.id
        await session.commit()
        return item.id, image_id


async def _add_asset(
    db_sessionmaker,
    item_id: uuid.UUID,
    *,
    data: bytes = PNG,
    prompt: str = "a bright classroom",
    attach: bool = True,
    created_at: dt.datetime | None = None,
) -> uuid.UUID:
    """Put one asset in the item's library, selected unless told otherwise.

    `attach=False` is the interesting case: an asset that exists but is not
    part of the post. Since D11 that is a real and reachable state, and it must
    mean the image does not go out.
    """
    async with db_sessionmaker() as session:
        item = await session.get(ContentItem, item_id)
        asset = MediaAsset(
            generation_group=item.generation_group,
            prompt=prompt,
            model="mock",
            data=data,
            **({"created_at": created_at} if created_at else {}),
        )
        session.add(asset)
        await session.flush()
        if attach:
            existing = (
                await session.execute(
                    select(ContentItemMedia).where(
                        ContentItemMedia.content_item_id == item_id
                    )
                )
            ).scalars().all()
            session.add(
                ContentItemMedia(
                    content_item_id=item_id,
                    media_asset_id=asset.id,
                    position=len(existing),
                )
            )
        await session.commit()
        return asset.id


def _service(session, publisher=None, **overrides) -> PublishService:
    return PublishService(session, make_settings(**overrides), publisher=publisher)


async def _audit_actions(session, item_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(AuditLog.action).where(AuditLog.entity_id == item_id)
    )
    return list(result.scalars())


# ── the happy path ──


async def test_publish_marks_the_item_published_and_records_the_permalink(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    publication = await _service(db_session, RecordingPublisher()).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert publication.status is PublishStatus.succeeded
    assert publication.external_post_id == "page_abc123"
    assert publication.permalink == "https://www.facebook.com/page_abc123"
    assert publication.completed_at is not None
    item = await db_session.get(ContentItem, item_id)
    assert item.status is ContentStatus.published


async def test_publish_sends_the_composed_text_not_the_bare_body(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker, hashtags=["#firstaid", "#wrcc"])
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    publisher = RecordingPublisher()

    await _service(db_session, publisher).publish(item_id, actor_id=uuid.uuid4())

    sent = publisher.requests[0].text
    assert sent == (
        "Enrol in our First Aid course this spring.\n\n"
        "Enrol today.\n\n"
        "#firstaid #wrcc"
    )


async def test_publish_prefers_the_edited_body(db_session, db_sessionmaker) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    async with db_sessionmaker() as session:
        item = await session.get(ContentItem, item_id)
        item.edited_body = "A human rewrote this."
        await session.commit()
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    publisher = RecordingPublisher()

    await _service(db_session, publisher).publish(item_id, actor_id=uuid.uuid4())

    assert publisher.requests[0].text.startswith("A human rewrote this.")


async def test_publish_passes_a_signed_url_and_jpeg_bytes(
    db_session, db_sessionmaker
) -> None:
    # Instagram fetches a URL; Facebook and LinkedIn upload bytes. Both are
    # offered so each publisher takes what its platform needs — and the bytes
    # are JPEG, matching exactly what the signed URL would serve.
    item_id, image_id = await _make_item(db_sessionmaker, with_image=True)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    publisher = RecordingPublisher()

    publication = await _service(db_session, publisher).publish(
        item_id, actor_id=uuid.uuid4()
    )

    request = publisher.requests[0]
    assert len(request.images) == 1
    image = request.images[0]
    assert image.url is not None
    assert str(image_id) in image.url
    assert "sig=" in image.url
    assert image.data.startswith(JPEG_MAGIC)
    assert image.data != PNG  # converted, not the stored PNG

    media = await _service(db_session).published_media_ids([publication.id])
    assert media[publication.id] == [str(image_id)]


async def test_an_unreadable_image_is_refused_before_any_attempt(
    db_session, db_sessionmaker
) -> None:
    # A refusal, not a failed publish: nothing was sent, so nothing is recorded.
    item_id, _ = await _make_item(db_sessionmaker, with_image=False)
    await _add_asset(db_sessionmaker, item_id, data=b"not an image", prompt="corrupt")
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    with pytest.raises(PublishNotAllowedError, match="not a readable image"):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4()
        )

    attempts = (
        await db_session.execute(
            select(ContentPublication).where(
                ContentPublication.content_item_id == item_id
            )
        )
    ).scalars().all()
    assert attempts == []


async def test_instagram_blocks_an_image_shaped_outside_its_spec(
    db_session, db_sessionmaker
) -> None:
    # We can downscale and convert, but we will not crop someone's image to
    # fit — an unpublishable ratio has to reach the operator.
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (600, 1800), (20, 92, 63)).save(buffer, format="PNG")
    item_id, _ = await _make_item(
        db_sessionmaker, platform=ContentPlatform.instagram, with_image=False
    )
    await _add_asset(
        db_sessionmaker,
        item_id,
        data=buffer.getvalue(),
        prompt="a very tall image",
    )
    await connect_social_account(db_sessionmaker, ContentPlatform.instagram)

    with pytest.raises(PublishNotAllowedError, match="ratio"):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4()
        )


async def test_facebook_does_not_apply_the_instagram_image_spec(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker, with_image=True)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    publication = await _service(db_session, RecordingPublisher()).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert publication.status is PublishStatus.succeeded


async def test_publish_still_works_without_a_public_host(
    db_session, db_sessionmaker
) -> None:
    # No PUBLIC_API_BASE_URL: Facebook can still post text, and LinkedIn takes
    # raw bytes. Only Instagram truly needs the URL, and its publisher decides.
    item_id, _ = await _make_item(db_sessionmaker, with_image=True)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    publisher = RecordingPublisher()

    publication = await _service(
        db_session, publisher, public_api_base_url=""
    ).publish(item_id, actor_id=uuid.uuid4())

    assert publication.status is PublishStatus.succeeded
    assert publisher.requests[0].images[0].url is None
    assert publisher.requests[0].images[0].data.startswith(JPEG_MAGIC)


async def test_publish_sends_the_selection_in_order_not_the_newest_image(
    db_session, db_sessionmaker
) -> None:
    # Before D11 the *most recent* image went out, silently. Now the post sends
    # what is selected, in the selected order — so a newer image added to the
    # library afterwards does not quietly displace the chosen one.
    item_id, first_image_id = await _make_item(db_sessionmaker, with_image=True)
    second_id = await _add_asset(db_sessionmaker, item_id, prompt="a second image")
    await _add_asset(
        db_sessionmaker,
        item_id,
        prompt="a newer image nobody selected",
        attach=False,
        created_at=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5),
    )
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    publisher = RecordingPublisher()

    publication = await _service(db_session, publisher).publish(
        item_id, actor_id=uuid.uuid4()
    )

    media = await _service(db_session).published_media_ids([publication.id])
    assert media[publication.id] == [str(first_image_id), str(second_id)]
    assert len(publisher.requests[0].images) == 2


async def test_an_unselected_image_is_not_published(
    db_session, db_sessionmaker
) -> None:
    # The other half of the same rule: an asset sitting in the library that
    # nobody ticked must not reach the network.
    item_id, _ = await _make_item(db_sessionmaker, with_image=False)
    await _add_asset(db_sessionmaker, item_id, prompt="never chosen", attach=False)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    publisher = RecordingPublisher()

    publication = await _service(db_session, publisher).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert publisher.requests[0].images == ()
    media = await _service(db_session).published_media_ids([publication.id])
    assert media == {}


async def test_publish_writes_an_audit_row(db_session, db_sessionmaker) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    await _service(db_session, RecordingPublisher()).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert "content_published" in await _audit_actions(db_session, item_id)


async def test_request_summary_never_carries_the_token(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    publication = await _service(db_session, RecordingPublisher()).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert TEST_ACCESS_TOKEN not in str(publication.request_summary)
    assert publication.request_summary["chars"] > 0
    assert publication.request_summary["destination"] == (
        "Western Riverina Community College"
    )


# ── refusals: nothing attempted, nothing recorded ──


@pytest.mark.parametrize(
    "status",
    [ContentStatus.draft, ContentStatus.pending_approval, ContentStatus.rejected],
)
async def test_unapproved_items_are_refused(
    db_session, db_sessionmaker, status: ContentStatus
) -> None:
    item_id, _ = await _make_item(db_sessionmaker, status=status)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    with pytest.raises(PublishNotAllowedError):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4()
        )

    attempts = (
        await db_session.execute(
            select(ContentPublication).where(
                ContentPublication.content_item_id == item_id
            )
        )
    ).scalars().all()
    assert attempts == []


async def test_refused_without_a_connected_account(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    with pytest.raises(PublishNotAllowedError, match="Connect one in Settings"):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4()
        )


async def test_refused_when_the_token_has_expired(db_session, db_sessionmaker) -> None:
    item_id, _ = await _make_item(db_sessionmaker, platform=ContentPlatform.linkedin)
    await connect_social_account(
        db_sessionmaker,
        ContentPlatform.linkedin,
        token_expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=1),
    )
    with pytest.raises(PublishNotAllowedError, match="Reconnect it in Settings"):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4()
        )


async def test_instagram_without_an_image_is_refused(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(
        db_sessionmaker, platform=ContentPlatform.instagram, with_image=False
    )
    await connect_social_account(db_sessionmaker, ContentPlatform.instagram)
    with pytest.raises(PublishNotAllowedError, match="require an image"):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4()
        )


async def test_publishing_twice_is_refused_and_reports_the_permalink(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    service = _service(db_session, RecordingPublisher())
    await service.publish(item_id, actor_id=uuid.uuid4())

    with pytest.raises(AlreadyPublishedError) as excinfo:
        await service.publish(item_id, actor_id=uuid.uuid4())

    assert excinfo.value.permalink == "https://www.facebook.com/page_abc123"


async def test_an_image_from_another_generation_is_rejected(
    db_session, db_sessionmaker
) -> None:
    # The library is scoped to the generation group, so an asset from an
    # unrelated generation is not merely unselected — it is not on offer.
    item_id, _ = await _make_item(db_sessionmaker)
    _, other_image_id = await _make_item(db_sessionmaker, with_image=True)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    with pytest.raises(ImageNotFoundError):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4(), asset_ids=[other_image_id]
        )


# ── failures: attempted, recorded, retryable ──


async def test_failure_records_the_attempt_and_leaves_the_item_approved(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    publisher = FailingPublisher(
        PublishError("Error validating access token.", code="reauth")
    )

    publication = await _service(db_session, publisher).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert publication.status is PublishStatus.failed
    assert publication.error_code == "reauth"
    assert "access token" in publication.error
    assert publication.completed_at is not None
    item = await db_session.get(ContentItem, item_id)
    assert item.status is ContentStatus.approved  # still retryable


async def test_failure_writes_an_audit_row(db_session, db_sessionmaker) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    await _service(db_session, FailingPublisher(PublishError("nope"))).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert "content_publish_failed" in await _audit_actions(db_session, item_id)


async def test_an_unexpected_exception_still_lands_in_the_attempt_row(
    db_session, db_sessionmaker
) -> None:
    # A publisher bug must not leave a pending row hanging forever.
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)

    publication = await _service(
        db_session, FailingPublisher(ValueError("boom"))
    ).publish(item_id, actor_id=uuid.uuid4())

    assert publication.status is PublishStatus.failed
    assert publication.error_code == "transient"
    assert "boom" in publication.error


async def test_an_unexpected_exception_cannot_carry_a_token_into_the_record(
    db_session, db_sessionmaker
) -> None:
    """This branch stringifies an *unknown* exception into a persisted, API-visible
    field. httpx puts the full URL in some of its messages, and Graph carries the
    token in the query string, so the redaction has to be unconditional here
    rather than relying on every upstream raiser to have done it."""
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    leaky = RuntimeError(
        f"GET https://graph.facebook.com/v23.0/me?access_token={TEST_ACCESS_TOKEN}"
    )

    publication = await _service(db_session, FailingPublisher(leaky)).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert TEST_ACCESS_TOKEN not in (publication.error or "")
    assert "REDACTED" in (publication.error or "")


async def test_a_failed_attempt_can_be_retried(db_session, db_sessionmaker) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    await _service(db_session, FailingPublisher(PublishError("flaky"))).publish(
        item_id, actor_id=uuid.uuid4()
    )

    publication = await _service(db_session, RecordingPublisher()).publish(
        item_id, actor_id=uuid.uuid4()
    )

    assert publication.status is PublishStatus.succeeded
    assert len(await _service(db_session).list_publications(item_id)) == 2


# ── pending attempts ──


async def test_a_stale_pending_attempt_blocks_a_silent_retry(
    db_session, db_sessionmaker
) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    async with db_sessionmaker() as session:
        session.add(
            ContentPublication(
                content_item_id=item_id,
                status=PublishStatus.pending,
                created_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1),
            )
        )
        await session.commit()

    with pytest.raises(PublishNotAllowedError, match="never reported back"):
        await _service(db_session, RecordingPublisher()).publish(
            item_id, actor_id=uuid.uuid4()
        )


async def test_a_concurrent_attempt_is_refused_before_it_reaches_the_network(
    db_session, db_sessionmaker
) -> None:
    """Two requests race; the loser must be stopped by the database, not by luck.

    The application check is a read followed by a write, so two concurrent
    requests can both read "nothing in flight" before either writes. Stubbing
    the read to miss a row that does exist reproduces exactly what the losing
    request sees. It must fail on its INSERT — one row later and there would be
    two live posts with only one of them recorded.
    """
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    async with db_sessionmaker() as session:
        session.add(
            ContentPublication(
                content_item_id=item_id, status=PublishStatus.pending
            )
        )
        await session.commit()

    publisher = RecordingPublisher()
    service = _service(db_session, publisher)

    async def _blind_to_the_other_request(_item_id):
        return None

    service._pending_publication = _blind_to_the_other_request  # type: ignore[method-assign]

    with pytest.raises(PublishNotAllowedError, match="already under way"):
        await service.publish(item_id, actor_id=uuid.uuid4())

    # The point of the whole exercise: nothing was sent.
    assert publisher.requests == []


# ── history ──


async def test_list_publications_is_newest_first(db_session, db_sessionmaker) -> None:
    item_id, _ = await _make_item(db_sessionmaker)
    await connect_social_account(db_sessionmaker, ContentPlatform.facebook)
    failed = await _service(db_session, FailingPublisher(PublishError("first"))).publish(
        item_id, actor_id=uuid.uuid4()
    )
    # Age the first attempt: SQLite's CURRENT_TIMESTAMP only resolves to the
    # second, so back-to-back attempts would otherwise tie and the assertion
    # would be decided by a random UUID rather than by the ordering under test.
    failed.created_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    await db_session.commit()
    await _service(db_session, RecordingPublisher()).publish(
        item_id, actor_id=uuid.uuid4()
    )

    publications = await _service(db_session).list_publications(item_id)

    assert [p.status for p in publications] == [
        PublishStatus.succeeded,
        PublishStatus.failed,
    ]


async def test_list_publications_404s_for_an_unknown_item(db_session) -> None:
    from app.content.service import ContentItemNotFoundError

    with pytest.raises(ContentItemNotFoundError):
        await _service(db_session).list_publications(uuid.uuid4())
