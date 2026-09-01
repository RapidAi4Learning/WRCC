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
from app.db.models import ContentImage, ContentItem, ContentPublication, SocialAccount
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
from app.publishing.publishers.base import PublishRequest
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

    async def _resolve_image(
        self, item: ContentItem, image_id: uuid.UUID | None
    ) -> ContentImage | None:
        """Explicit image if given (and it belongs to this post), else the latest."""
        if image_id is not None:
            image = await self._session.get(ContentImage, image_id)
            if image is None or image.content_item_id != item.id:
                raise ImageNotFoundError(
                    f"Image {image_id} does not belong to content item {item.id}."
                )
            return image
        result = await self._session.execute(
            select(ContentImage)
            .where(ContentImage.content_item_id == item.id)
            .order_by(ContentImage.created_at.desc(), ContentImage.id.desc())
        )
        return result.scalars().first()

    def _is_stale(self, attempt: ContentPublication, now: dt.datetime) -> bool:
        created = attempt.created_at
        if created.tzinfo is None:  # SQLite round-trips naive datetimes
            created = created.replace(tzinfo=dt.UTC)
        age = (now - created).total_seconds()
        return age > self._settings.publish_pending_stale_seconds

    # ── preflight ──

    async def preflight(
        self, item_id: uuid.UUID, *, image_id: uuid.UUID | None = None
    ) -> tuple[
        ContentItem,
        SocialAccount | None,
        ContentImage | None,
        str,
        PreflightOutcome,
    ]:
        """Evaluate every rule without sending anything. Safe to call freely."""
        item = await self._get_item(item_id)
        account = await self._accounts.get_active(item.platform)
        image = await self._resolve_image(item, image_id)
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
                has_image=image is not None,
                image_problems=(
                    instagram_problems(image.data)
                    if image is not None and item.platform is ContentPlatform.instagram
                    else []
                ),
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
        return item, account, image, text, outcome

    # ── publish ──

    async def publish(
        self,
        item_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        image_id: uuid.UUID | None = None,
    ) -> ContentPublication:
        """Send the post and return the attempt record.

        Returns the record for **both** outcomes — a failed publish is a durable
        result, not an exception the caller should have to reconstruct. Refusals
        (unknown item, already published, preflight blockers) raise instead,
        because nothing was attempted and nothing was recorded.
        """
        item, account, image, text, outcome = await self.preflight(
            item_id, image_id=image_id
        )

        existing = await self._succeeded_publication(item.id)
        if existing is not None:
            raise AlreadyPublishedError(existing.permalink)
        if not outcome.ready:
            raise PublishNotAllowedError(outcome.blockers)
        assert account is not None  # preflight blocks when it is None

        resolved = self._accounts.resolve(account)
        image_url = self._image_url(image)
        # Converted before any attempt is recorded: an unreadable image is a
        # refusal, not a failed publish.
        image_jpeg = self._image_jpeg(image)
        publisher = self._publisher or get_publisher(item.platform, self._settings)

        attempt = ContentPublication(
            content_item_id=item.id,
            social_account_id=account.id,
            content_image_id=image.id if image is not None else None,
            status=PublishStatus.pending,
            request_summary={
                "platform": item.platform.value,
                "destination": account.display_name,
                "chars": len(text),
                "hashtags": len(item.hashtags or []),
                "has_image": image is not None,
            },
            attempted_by=actor_id,
        )
        self._session.add(attempt)
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
            image_url=image_url,
            image_bytes=image_jpeg,
            image_alt=image.prompt[:300] if image is not None else None,
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

    def _image_jpeg(self, image: ContentImage | None) -> bytes | None:
        """Convert the stored PNG once, for the networks that upload bytes.

        Doing it here rather than per-publisher means Facebook and LinkedIn
        receive exactly what the signed URL would hand Instagram, so the three
        posts cannot end up showing different renderings of the same image.
        """
        if image is None:
            return None
        try:
            return to_jpeg(image.data)
        except MediaConversionError as exc:
            raise PublishNotAllowedError([str(exc)]) from exc

    def _image_url(self, image: ContentImage | None) -> str | None:
        """Signed public URL for the networks that fetch the image themselves.

        A missing public host is not fatal here: LinkedIn uploads raw bytes and
        Facebook can post text-only, so the publisher decides whether the
        absence is a problem for its platform.
        """
        if image is None:
            return None
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
