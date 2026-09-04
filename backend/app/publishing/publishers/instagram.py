"""Publish to an Instagram Business account.

Three calls, not one:

1. ``POST /{ig}/media`` builds a *container* from a publicly fetchable image URL
2. poll the container until it reports ``FINISHED``
3. ``POST /{ig}/media_publish`` turns the container into a post

A carousel inserts one more layer: each image gets its own child container
(``is_carousel_item=true``, no caption), and a parent container names the
children and carries the caption. Only the parent is ever published.

Instagram cannot be handed image bytes — it fetches the URL from its own
servers — which is the entire reason the signed public image endpoint exists,
and why a carousel needs every one of its images signed at once.
Authentication uses the parent Facebook Page's token.
"""

from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.publishing.meta_graph import GraphClient, MetaGraphError
from app.publishing.publishers.base import (
    PublishError,
    PublishRequest,
    PublishResult,
)
from app.publishing.publishers.facebook import graph_error_to_publish_error
from app.publishing.publishers.retry import with_retries

# Container states that will never become publishable.
_DEAD_STATES = {"ERROR", "EXPIRED"}


class InstagramPublisher:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    def _client(self, access_token: str) -> GraphClient:
        return GraphClient(
            self._settings, access_token=access_token, transport=self._transport
        )

    async def publish(self, request: PublishRequest) -> PublishResult:
        if not request.images:
            raise PublishError(
                "Instagram posts require an image.", code="invalid"
            )
        missing = [
            index + 1 for index, image in enumerate(request.images) if not image.url
        ]
        if missing:
            raise PublishError(
                "Instagram fetches images from a public URL, and this backend "
                "has no public address. Set PUBLIC_API_BASE_URL to a reachable "
                "https origin.",
                code="unreachable_media",
            )
        # Only the containers are retried. A container is private scaffolding —
        # building three of them costs nothing, and an abandoned one expires on
        # its own. The publish step below is what puts a post on the feed, so it
        # runs exactly once, for a carousel exactly as for a single image.
        creation_id = await with_retries(
            lambda: self._prepare_container(request),
            attempts=self._settings.publish_max_attempts,
            base_delay=self._settings.publish_retry_base_delay_seconds,
            description="Instagram container",
        )
        return await self._publish_container(request, creation_id)

    async def _prepare_container(self, request: PublishRequest) -> str:
        """Build the publishable container. Safe to repeat.

        One image is a plain media container, as it always was. Two or more
        become a carousel: a child container per image, then a parent that
        names them. The children carry no caption — the caption belongs to the
        parent, and Instagram ignores it on a child.
        """
        if len(request.images) >= 2:
            return await self._prepare_carousel(request)

        client = self._client(request.account.access_token)
        image = request.images[0]
        try:
            created = await client.post(
                f"/{request.account.external_id}/media",
                data={"image_url": image.url, "caption": request.text},
            )
            creation_id = created.get("id")
            if not creation_id:
                raise PublishError(
                    "Instagram did not return a media container id.", code="transient"
                )
            await self._await_container(client, str(creation_id))
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc
        return str(creation_id)

    async def _prepare_carousel(self, request: PublishRequest) -> str:
        """Children first, then the parent that binds them, in order."""
        client = self._client(request.account.access_token)
        ig_id = request.account.external_id
        try:
            child_ids: list[str] = []
            for index, image in enumerate(request.images):
                created = await client.post(
                    f"/{ig_id}/media",
                    data={"image_url": image.url, "is_carousel_item": "true"},
                )
                child_id = created.get("id")
                if not child_id:
                    raise PublishError(
                        f"Instagram did not return a container id for image "
                        f"{index + 1}.",
                        code="transient",
                    )
                await self._await_container(client, str(child_id))
                child_ids.append(str(child_id))

            parent = await client.post(
                f"/{ig_id}/media",
                data={
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_ids),
                    "caption": request.text,
                },
            )
            parent_id = parent.get("id")
            if not parent_id:
                raise PublishError(
                    "Instagram did not return a carousel container id.",
                    code="transient",
                )
            await self._await_container(client, str(parent_id))
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc
        return str(parent_id)

    async def _publish_container(
        self, request: PublishRequest, creation_id: str
    ) -> PublishResult:
        """Turn the container into a live post. Called once, never retried."""
        client = self._client(request.account.access_token)
        try:
            published = await client.post(
                f"/{request.account.external_id}/media_publish",
                data={"creation_id": creation_id},
            )
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc

        media_id = published.get("id")
        if not media_id:
            raise PublishError(
                "Instagram accepted the post but returned no media id, so it is "
                "probably live and we cannot link to it. Check the account before "
                "publishing again.",
                code="ambiguous",
            )
        return PublishResult(
            external_post_id=str(media_id),
            permalink=await self._permalink(client, str(media_id)),
        )

    async def _await_container(self, client: GraphClient, creation_id: str) -> None:
        """Block until the container is publishable, or explain why it never will be."""
        for attempt in range(self._settings.instagram_container_poll_attempts):
            payload = await client.get(
                f"/{creation_id}", params={"fields": "status_code"}
            )
            state = payload.get("status_code")
            # Images are usually finished on creation, and some responses omit
            # the field entirely — treat that as ready rather than polling out.
            if state in (None, "FINISHED"):
                return
            if state in _DEAD_STATES:
                raise PublishError(
                    f"Instagram rejected the image while processing it ({state}). "
                    "Check the image meets Instagram's size and ratio rules.",
                    code="invalid",
                )
            if attempt + 1 < self._settings.instagram_container_poll_attempts:
                await asyncio.sleep(
                    self._settings.instagram_container_poll_delay_seconds
                )
        raise PublishError(
            "Instagram did not finish processing the image in time.", code="transient"
        )

    async def _permalink(self, client: GraphClient, media_id: str) -> str | None:
        """Best-effort: the post is already live, so a failure here costs nothing."""
        try:
            payload = await client.get(f"/{media_id}", params={"fields": "permalink"})
        except MetaGraphError:
            return None
        link = payload.get("permalink")
        return str(link) if link else None

    async def verify(self, account) -> None:
        try:
            await self._client(account.access_token).get(
                f"/{account.external_id}", params={"fields": "id,username"}
            )
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc
