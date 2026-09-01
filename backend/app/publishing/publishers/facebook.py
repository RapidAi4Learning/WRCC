"""Publish to a Facebook Page.

Two shapes: a text post to ``/{page}/feed``, or a photo post to
``/{page}/photos`` carrying the caption.

The photo path uploads **raw bytes** rather than pointing Graph at a URL. The
reference implementation used a URL, but bytes remove the requirement that this
backend be publicly reachable, so Facebook publishing works from a laptop and
the signed public image endpoint is left as Instagram's problem alone.
"""

from __future__ import annotations

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
        return await with_retries(
            lambda: self._publish_once(request),
            attempts=self._settings.publish_max_attempts,
            base_delay=self._settings.publish_retry_base_delay_seconds,
            description="Facebook publish",
        )

    async def _publish_once(self, request: PublishRequest) -> PublishResult:
        client = self._client(request.account.access_token)
        page_id = request.account.external_id
        try:
            if request.image_bytes:
                payload = await client.post_files(
                    f"/{page_id}/photos",
                    data={"caption": request.text},
                    files={"source": ("post.jpg", request.image_bytes, "image/jpeg")},
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
