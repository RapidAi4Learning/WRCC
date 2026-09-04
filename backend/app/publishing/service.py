"""Publish orchestration — the one place a post becomes irreversible.

Publishing is the only action in this application with a side effect on someone
else's server that we cannot undo. Two consequences shape the code below:

1. The ``pending`` attempt row is committed *before* the network call. Every
   other service here commits once at the end; this one deliberately does not,
   because an attempt that dies mid-flight must leave evidence. "We may have
   posted and lost the response" is a different situation from "we never
   tried", and only a committed row can tell them apart afterwards.

2. A failed attempt leaves the item in ``approved`` so it stays retryable,
   while a successful one moves it to ``published``, from which the only
   remaining move is ``archived``.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.content.repository import ContentRepository
from app.content.service import ContentItemNotFoundError
from app.content.state import assert_transition
from app.db.enums import ContentPlatform, ContentStatus, PublishStatus
from app.db.models import (
    ContentItem,
    ContentItemMedia,
    ContentPublication,
    ContentPublicationMedia,
    MediaAsset,
    SocialAccount,
)
from app.publishing.accounts import SocialAccountService, is_token_expired
from app.publishing.media import (
    MediaConversionError,
    MediaSigningError,
    instagram_problems,
    sign_image_url,
    to_jpeg,
)
from app.publishing.meta_graph import redact_access_token
from app.publishing.publishers import Publisher, PublishError, get_publisher
from app.publishing.publishers.base import PublishImage, PublishRequest
from app.publishing.rules import (
    PreflightContext,
    PreflightOutcome,
    compose_post_text,
    preflight,
)

logger = logging.getLogger(__name__)


class PublishNotAllowedError(RuntimeError):
    """Preflight refused the request; ``blockers`` says why. Nothing was sent."""

    def __init__(self, blockers: list[str]) -> None:
        super().__init__(" ".join(blockers))
        self.blockers = blockers


class AlreadyPublishedError(RuntimeError):
    """This item is already live; ``permalink`` points at it."""

    def __init__(self, permalink: str | None) -> None:
        super().__init__("This post has already been published.")
        self.permalink = permalink


class ImageNotFoundError(LookupError):
    """The requested image does not exist, or belongs to a different post."""


class PublishService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        publisher: Publisher | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._repo = ContentRepository(session)
        self._accounts = SocialAccountService(session, settings)
        # Injected in tests to script success/failure without a network.
        self._publisher = publisher

    # ── reads ──

    async def _get_item(self, item_id: uuid.UUID) -> ContentItem:
        item = await self._repo.get(item_id)
        if item is None:
            raise ContentItemNotFoundError(f"Content item {item_id} not found.")
        return item

    async def _succeeded_publication(
        self, item_id: uuid.UUID
    ) -> ContentPublication | None:
        result = await self._session.execute(
            select(ContentPublication).where(
                ContentPublication.content_item_id == item_id,
                ContentPublication.status == PublishStatus.succeeded,
            )
        )
        return result.scalars().first()

    async def _pending_publication(
        self, item_id: uuid.UUID
    ) -> ContentPublication | None:
        result = await self._session.execute(
            select(ContentPublication)
            .where(
                ContentPublication.content_item_id == item_id,
                ContentPublication.status == PublishStatus.pending,
            )
            .order_by(ContentPublication.created_at.desc())
        )
        return result.scalars().first()

    async def list_publications(
        self, item_id: uuid.UUID
    ) -> list[ContentPublication]:
        await self._get_item(item_id)  # 404 for unknown posts, not an empty list
        result = await self._session.execute(
            select(ContentPublication)
            .where(ContentPublication.content_item_id == item_id)
            .order_by(
                ContentPublication.created_at.desc(), ContentPublication.id.desc()
            )
        )
        return list(result.scalars())

    async def published_media_ids(
        self, publication_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[str]]:
        """Which assets each attempt sent, in order. One query for the batch."""
        if not publication_ids:
            return {}
        result = await self._session.execute(
            select(ContentPublicationMedia)
            .where(ContentPublicationMedia.publication_id.in_(publication_ids))
            .order_by(
                ContentPublicationMedia.publication_id,
                ContentPublicationMedia.position,
            )
        )
        grouped: dict[uuid.UUID, list[str]] = {}
        for row in result.scalars():
            if row.media_asset_id is None:
                continue
            grouped.setdefault(row.publication_id, []).append(str(row.media_asset_id))
        return grouped

    async def _available_ids(self, item: ContentItem) -> set[uuid.UUID]:
        """Every asset this item is allowed to publish — its generation group."""
        if item.generation_group is None:
            result = await self._session.execute(
                select(ContentItemMedia.media_asset_id).where(
                    ContentItemMedia.content_item_id == item.id
                )
            )
            return set(result.scalars())
        result = await self._session.execute(
            select(MediaAsset.id).where(
                MediaAsset.generation_group == item.generation_group
            )
        )
        return set(result.scalars())

    async def _resolve_media(
        self, item: ContentItem, asset_ids: list[uuid.UUID] | None
    ) -> list[MediaAsset]:
        """The images this post will send, in publish order.

        An explicit list from the request wins (the publish dialog lets the
        operator reorder without saving first); otherwise the item's stored
        selection. Order is preserved exactly as given — on a carousel it is
        what the reader scrolls through.
        """
        if asset_ids is not None:
            if not asset_ids:
                return []
            available = await self._available_ids(item)
            unknown = [str(a) for a in asset_ids if a not in available]
            if unknown:
                raise ImageNotFoundError(
                    f"Image(s) {', '.join(unknown)} are not available to content "
                    f"item {item.id}."
                )
            result = await self._session.execute(
                select(MediaAsset).where(MediaAsset.id.in_(asset_ids))
            )
            by_id = {asset.id: asset for asset in result.scalars()}
            return [by_id[a] for a in asset_ids if a in by_id]

        rows = await self._session.execute(
            select(ContentItemMedia)
            .where(ContentItemMedia.content_item_id == item.id)
            .order_by(ContentItemMedia.position)
        )
        selection = list(rows.scalars())
        if not selection:
            return []
        result = await self._session.execute(
            select(MediaAsset).where(
                MediaAsset.id.in_([row.media_asset_id for row in selection])
            )
        )
        by_id = {asset.id: asset for asset in result.scalars()}
        return [
            by_id[row.media_asset_id]
            for row in selection
            if row.media_asset_id in by_id
        ]

    async def _unselected_count(
        self, item: ContentItem, selected: list[MediaAsset]
    ) -> int:
        """Assets in the library this post is leaving behind."""
        available = await self._available_ids(item)
        return max(0, len(available - {asset.id for asset in selected}))

    def _is_stale(self, attempt: ContentPublication, now: dt.datetime) -> bool:
        created = attempt.created_at
        if created.tzinfo is None:  # SQLite round-trips naive datetimes
            created = created.replace(tzinfo=dt.UTC)
        age = (now - created).total_seconds()
        return age > self._settings.publish_pending_stale_seconds

    # ── preflight ──

    def _image_problems(
        self, item: ContentItem, images: list[MediaAsset]
    ) -> list[str]:
        """Per-image spec violations, each carrying its own position.

        Only Instagram enforces a shape, and on a carousel it enforces it on
        every child — an eighth image outside the accepted ratio fails the post
        as surely as the first would, so an anonymous list of problems would
        leave the operator hunting for which picture to replace.
        """
        if item.platform is not ContentPlatform.instagram:
            return []
        problems: list[str] = []
        for index, image in enumerate(images):
            prefix = f"Image {index + 1}: " if len(images) > 1 else ""
            problems.extend(
                f"{prefix}{problem}" for problem in instagram_problems(image.data)
            )
        return problems

    async def preflight(
        self, item_id: uuid.UUID, *, asset_ids: list[uuid.UUID] | None = None
    ) -> tuple[
        ContentItem,
        SocialAccount | None,
        list[MediaAsset],
        str,
        PreflightOutcome,
    ]:
        """Evaluate every rule without sending anything. Safe to call freely."""
        item = await self._get_item(item_id)
        account = await self._accounts.get_active(item.platform)
        images = await self._resolve_media(item, asset_ids)
        text = compose_post_text(
            item.edited_body or item.generated_body,
            item.call_to_action,
            list(item.hashtags or []),
        )
        pending = await self._pending_publication(item.id)
        now = dt.datetime.now(dt.UTC)
        outcome = preflight(
            PreflightContext(
                platform=item.platform,
                status=item.status,
                text=text,
                hashtag_count=len(item.hashtags or []),
                image_count=len(images),
                image_problems=self._image_problems(item, images),
                unselected_available=await self._unselected_count(item, images),
                account_connected=account is not None,
                account_token_expired=(
                    account is not None and is_token_expired(account, now=now)
                ),
                already_published=await self._succeeded_publication(item.id) is not None,
                has_pending_attempt=pending is not None,
                pending_attempt_is_stale=(
                    pending is not None and self._is_stale(pending, now)
                ),
            )
        )
        return item, account, images, text, outcome

    # ── publish ──

    async def publish(
        self,
        item_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        asset_ids: list[uuid.UUID] | None = None,
    ) -> ContentPublication:
        """Send the post and return the attempt record.

        Returns the record for **both** outcomes — a failed publish is a durable
        result, not an exception the caller should have to reconstruct. Refusals
        (unknown item, already published, preflight blockers) raise instead,
        because nothing was attempted and nothing was recorded.
        """
        item, account, images, text, outcome = await self.preflight(
            item_id, asset_ids=asset_ids
        )

        existing = await self._succeeded_publication(item.id)
        if existing is not None:
            raise AlreadyPublishedError(existing.permalink)
        if not outcome.ready:
            raise PublishNotAllowedError(outcome.blockers)
        assert account is not None  # preflight blocks when it is None

        resolved = self._accounts.resolve(account)
        # Every URL is signed here, from one clock, so the last child of a
        # ten-image carousel is still valid when Meta gets to it. Bytes are
        # converted before any attempt is recorded: an unreadable image is a
        # refusal, not a failed publish.
        publish_images = tuple(
            PublishImage(
                data=self._image_jpeg(image),
                url=self._image_url(image),
                alt=(image.alt_text or image.prompt or image.filename or None),
            )
            for image in images
        )
        publisher = self._publisher or get_publisher(item.platform, self._settings)

        attempt = ContentPublication(
            # Assigned here rather than at flush: the media rows below reference
            # it, and the flush that would generate it must not happen outside
            # the try that catches the in-flight unique violation.
            id=uuid.uuid4(),
            content_item_id=item.id,
            social_account_id=account.id,
            status=PublishStatus.pending,
            request_summary={
                "platform": item.platform.value,
                "destination": account.display_name,
                "chars": len(text),
                "hashtags": len(item.hashtags or []),
                "image_count": len(images),
            },
            attempted_by=actor_id,
        )
        self._session.add(attempt)
        # Recorded alongside the pending row and inside the same pre-call
        # commit: if the attempt dies mid-flight, "what did we send?" must be
        # answerable from the database alone.
        self._session.add_all(
            ContentPublicationMedia(
                publication_id=attempt.id,
                media_asset_id=image.id,
                position=position,
            )
            for position, image in enumerate(images)
        )
        # Committed before the call on purpose — see the module docstring.
        try:
            await self._session.commit()
        except IntegrityError as exc:
            # `uq_content_publications_in_flight` fired: another request claimed
            # this item between our preflight read and this insert. Losing that
            # race must happen *here*, before the network call — one row later
            # would mean two live posts and only one of them recorded.
            await self._session.rollback()
            raise PublishNotAllowedError(
                [
                    "Another publish attempt for this post is already under way. "
                    "Wait for it to finish before trying again."
                ]
            ) from exc

        request = PublishRequest(
            text=text,
            account=resolved,
            images=publish_images,
            link=item.reference_url,
        )

        try:
            result = await publisher.publish(request)
        except PublishError as exc:
            return await self._record_failure(attempt, item, exc, actor_id=actor_id)
        except Exception as exc:  # noqa: BLE001 - any failure must land in the row
            logger.exception("Unexpected failure publishing content item %s", item.id)
            # Redacted because this branch stringifies an *unknown* exception
            # into a field we persist and hand back over the API. Nothing
            # reaching here leaks a token today, but the guarantee would be one
            # `raise_for_status()` upstream away from breaking silently —
            # httpx puts the full URL, query string included, in that message.
            return await self._record_failure(
                attempt,
                item,
                PublishError(
                    redact_access_token(f"Unexpected publishing failure: {exc}"),
                    code="transient",
                ),
                actor_id=actor_id,
            )

        attempt.status = PublishStatus.succeeded
        attempt.external_post_id = result.external_post_id
        attempt.permalink = result.permalink
        attempt.completed_at = dt.datetime.now(dt.UTC)
        assert_transition(item.status, ContentStatus.published)
        item.status = ContentStatus.published
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_published",
            entity_type="content_item",
            entity_id=item.id,
            payload_diff={
                "platform": item.platform.value,
                "publication_id": str(attempt.id),
                "external_post_id": result.external_post_id,
                "permalink": result.permalink,
            },
        )
        await self._session.commit()
        return attempt

    def _image_jpeg(self, image: MediaAsset) -> bytes:
        """Convert the stored bytes once, for the networks that upload them.

        Doing it here rather than per-publisher means Facebook and LinkedIn
        receive exactly what the signed URL would hand Instagram, so the three
        posts cannot end up showing different renderings of the same image.
        """
        try:
            return to_jpeg(image.data)
        except MediaConversionError as exc:
            raise PublishNotAllowedError([str(exc)]) from exc

    def _image_url(self, image: MediaAsset) -> str | None:
        """Signed public URL for the networks that fetch the image themselves.

        A missing public host is not fatal here: LinkedIn uploads raw bytes and
        Facebook can post text-only, so the publisher decides whether the
        absence is a problem for its platform.
        """
        try:
            return sign_image_url(self._settings, image_id=image.id)
        except MediaSigningError as exc:
            logger.warning("No public image URL available: %s", exc)
            return None

    async def _record_failure(
        self,
        attempt: ContentPublication,
        item: ContentItem,
        error: PublishError,
        *,
        actor_id: uuid.UUID,
    ) -> ContentPublication:
        """Persist the failure; the item stays ``approved`` so it can be retried."""
        attempt.status = PublishStatus.failed
        attempt.error = str(error)
        attempt.error_code = error.code
        attempt.completed_at = dt.datetime.now(dt.UTC)
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_publish_failed",
            entity_type="content_item",
            entity_id=item.id,
            payload_diff={
                "platform": item.platform.value,
                "publication_id": str(attempt.id),
                "error_code": error.code,
                "error": str(error)[:500],
            },
        )
        await self._session.commit()
        return attempt
