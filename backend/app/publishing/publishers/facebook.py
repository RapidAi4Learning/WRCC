"""Publish to a Facebook Page.

Three shapes, by image count:

- **none** — a text post to ``/{page}/feed``
- **one** — a photo post to ``/{page}/photos`` carrying the caption
- **several** — each photo uploaded ``published=false``, then one ``/{page}/feed``
  call binding them together through ``attached_media``

The photo paths upload **raw bytes** rather than pointing Graph at a URL. The
reference implementation used a URL, but bytes remove the requirement that this
backend be publicly reachable, so Facebook publishing works from a laptop and
the signed public image endpoint is left as Instagram's problem alone.

The retry boundary in the multi-photo shape is the one Instagram already uses
for containers. An unpublished photo is private scaffolding: it appears nowhere
on the Page, expires on its own if the run dies before the feed call, and can
therefore be uploaded again freely. The ``/feed`` call that turns the set into a
story is what a reader sees, so it runs exactly once.
"""

from __future__ import annotations

import json

import httpx

from app.config import Settings
from app.publishing.meta_graph import (
    GraphClient,
    MetaAuthError,
    MetaGraphError,
    MetaRateLimitError,
    MetaTransientError,
)
from app.publishing.publishers.base import (
    PublishError,
    PublishRequest,
    PublishResult,
)
from app.publishing.publishers.retry import with_retries


def graph_error_to_publish_error(exc: MetaGraphError) -> PublishError:
    """Translate the Graph taxonomy into the codes the UI reacts to."""
    if isinstance(exc, MetaAuthError):
        return PublishError(
            f"{exc} Reconnect the account in Settings.", code="reauth"
        )
    if isinstance(exc, MetaRateLimitError):
        return PublishError(f"{exc} Try again shortly.", code="rate_limited")
    if isinstance(exc, MetaTransientError):
        return PublishError(str(exc), code="transient")
    return PublishError(str(exc), code="invalid")


def permalink_for(post_id: str) -> str:
    return f"https://www.facebook.com/{post_id}"


class FacebookPublisher:
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
        if len(request.images) >= 2:
            return await self._publish_multi_photo(request)
        return await with_retries(
            lambda: self._publish_once(request),
            attempts=self._settings.publish_max_attempts,
            base_delay=self._settings.publish_retry_base_delay_seconds,
            description="Facebook publish",
        )

    async def _publish_multi_photo(self, request: PublishRequest) -> PublishResult:
        """Stage every photo unpublished, then bind them into one story."""
        media_ids = await with_retries(
            lambda: self._upload_unpublished(request),
            attempts=self._settings.publish_max_attempts,
            base_delay=self._settings.publish_retry_base_delay_seconds,
            description="Facebook photo upload",
        )
        return await self._attach_and_publish(request, media_ids)

    async def _upload_unpublished(self, request: PublishRequest) -> list[str]:
        """Upload the photos without publishing them. Safe to repeat."""
        client = self._client(request.account.access_token)
        page_id = request.account.external_id
        media_ids: list[str] = []
        try:
            for index, image in enumerate(request.images):
                payload = await client.post_files(
                    f"/{page_id}/photos",
                    data={"published": "false", "alt_text_custom": image.alt or ""},
                    files={
                        "source": (f"post-{index + 1}.jpg", image.data, "image/jpeg")
                    },
                )
                photo_id = payload.get("id")
                if not photo_id:
                    raise PublishError(
                        f"Facebook did not return an id for image {index + 1}.",
                        code="transient",
                    )
                media_ids.append(str(photo_id))
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc
        return media_ids

    async def _attach_and_publish(
        self, request: PublishRequest, media_ids: list[str]
    ) -> PublishResult:
        """The one call that puts the post on the Page. Never retried."""
        client = self._client(request.account.access_token)
        data: dict[str, str] = {"message": request.text}
        # Graph reads `attached_media[0]`, `attached_media[1]`, … as indexed
        # form fields, not as one JSON array.
        for index, media_id in enumerate(media_ids):
            data[f"attached_media[{index}]"] = json.dumps({"media_fbid": media_id})
        try:
            payload = await client.post(
                f"/{request.account.external_id}/feed", data=data
            )
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc

        post_id = payload.get("id")
        if not post_id:
            raise PublishError(
                "Facebook accepted the multi-photo post but returned no id, so "
                "it is probably live and we cannot link to it. Check the Page "
                "before publishing again.",
                code="ambiguous",
            )
        return PublishResult(
            external_post_id=str(post_id), permalink=permalink_for(str(post_id))
        )

    async def _publish_once(self, request: PublishRequest) -> PublishResult:
        client = self._client(request.account.access_token)
        page_id = request.account.external_id
        image = request.first_image
        try:
            if image is not None:
                payload = await client.post_files(
                    f"/{page_id}/photos",
                    data={"caption": request.text},
                    files={"source": ("post.jpg", image.data, "image/jpeg")},
                )
                # /photos returns the photo id in `id` and the story id in
                # `post_id`; the story is what a permalink should point at.
                post_id = payload.get("post_id") or payload.get("id")
            else:
                data = {"message": request.text}
                if request.link:
                    data["link"] = request.link
                payload = await client.post(f"/{page_id}/feed", data=data)
                post_id = payload.get("id")
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc

        if not post_id:
            # Graph answered without an error, so the post is almost certainly
            # live — we just cannot name it. Never retry this.
            raise PublishError(
                "Facebook accepted the post but returned no id, so it is probably "
                "live and we cannot link to it. Check the Page before publishing "
                "again.",
                code="ambiguous",
            )
        return PublishResult(
            external_post_id=str(post_id), permalink=permalink_for(str(post_id))
        )

    async def verify(self, account) -> None:
        """Confirm the Page token still works — a token can die silently."""
        try:
            await self._client(account.access_token).get(
                f"/{account.external_id}", params={"fields": "id,name"}
            )
        except MetaGraphError as exc:
            raise graph_error_to_publish_error(exc) from exc
