"""Publish to a LinkedIn Company Page (or a member profile — decision D6).

An image post is three legs: initialize an upload, PUT the bytes to the URL
LinkedIn hands back, then create the post referencing the returned image URN.
Several images repeat the first two legs per image and change the third:
``content.media`` becomes ``content.multiImage.images``. LinkedIn models the two
as different shapes rather than as a list of length one, so the single-image
request stays exactly what it was.

The post id does **not** come back in the response body — it arrives in the
``x-restli-id`` header, which is easy to miss and leaves you with a successful
post you cannot link to.

``multiImage`` rides the same Community Management API approval the
single-image path already needs, and the payload shape is versioned — confirm
both against ``LINKEDIN_API_VERSION`` before going live.
"""

from __future__ import annotations

from functools import partial

import httpx

from app.config import Settings
from app.publishing.publishers.base import (
    PublishError,
    PublishRequest,
    PublishResult,
)
from app.publishing.publishers.retry import with_retries

API_BASE = "https://api.linkedin.com"

# LinkedIn's "little text" format reserves these; every one must be
# backslash-escaped in `commentary` or the request is rejected. Generated posts
# routinely contain '(', ')' and '#', so this is not a rare edge case.
_RESERVED = set("\\|{}@[]()<>#*_~")


def escape_commentary(text: str) -> str:
    """Escape the reserved characters in LinkedIn's little-text format."""
    return "".join(f"\\{char}" if char in _RESERVED else char for char in text)


def permalink_for(post_urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{post_urn}"


class LinkedInPublisher:
    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport, timeout=self._settings.publish_timeout_seconds
        )

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": self._settings.linkedin_api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    def _author(self, request: PublishRequest) -> str:
        configured = request.account.metadata.get("author_urn")
        if configured:
            return str(configured)
        return f"urn:li:organization:{request.account.external_id}"

    async def publish(self, request: PublishRequest) -> PublishResult:
        token = request.account.access_token
        author = self._author(request)

        # Only the uploads are retried. An uploaded image is not a post — a
        # second copy is invisible to everyone. Creating the post is not
        # repeatable, so it happens once, below, outside the retry. Each image
        # is retried on its own rather than the batch: re-uploading four
        # because the fifth was throttled is waste, not safety.
        image_urns: list[str] = []
        for index, image in enumerate(request.images):
            image_urns.append(
                await with_retries(
                    partial(
                        self._upload_image,
                        image.data,
                        owner=author,
                        token=token,
                    ),
                    attempts=self._settings.publish_max_attempts,
                    base_delay=self._settings.publish_retry_base_delay_seconds,
                    description=f"LinkedIn image {index + 1} upload",
                )
            )
        return await self._create_post(
            request, author=author, token=token, image_urns=image_urns
        )

    def _content_for(
        self, request: PublishRequest, image_urns: list[str]
    ) -> dict | None:
        """The post's `content` block: absent, single `media`, or `multiImage`.

        LinkedIn treats one image and several as different shapes rather than a
        list of length one, so the single-image path stays byte-identical to
        what it was before carousels existed.
        """
        if not image_urns:
            return None
        if len(image_urns) == 1:
            media: dict = {"id": image_urns[0]}
            alt = request.images[0].alt
            if alt:
                media["altText"] = alt
            return {"media": media}

        images = []
        # strict: one URN was collected per image, in order, a few lines up —
        # a length mismatch here would mean an image silently lost its upload.
        for urn, image in zip(image_urns, request.images, strict=True):
            entry: dict = {"id": urn}
            if image.alt:
                entry["altText"] = image.alt
            images.append(entry)
        return {"multiImage": {"images": images}}

    async def _create_post(
        self,
        request: PublishRequest,
        *,
        author: str,
        token: str,
        image_urns: list[str],
    ) -> PublishResult:
        body: dict = {
            "author": author,
            "commentary": escape_commentary(request.text),
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        content = self._content_for(request, image_urns)
        if content is not None:
            body["content"] = content

        async with self._client() as client:
            response = await client.post(
                f"{API_BASE}/rest/posts", json=body, headers=self._headers(token)
            )
        if response.is_error:
            raise self._error(response, "create the post")

        # The id lives in a header, not the body.
        post_urn = response.headers.get("x-restli-id") or response.headers.get(
            "x-linkedin-id"
        )
        if not post_urn:
            raise PublishError(
                "LinkedIn accepted the post but returned no id, so it is probably "
                "live and we cannot link to it. Check the page before publishing "
                "again.",
                code="ambiguous",
            )
        return PublishResult(
            external_post_id=post_urn, permalink=permalink_for(post_urn)
        )

    async def _upload_image(self, image: bytes, *, owner: str, token: str) -> str:
        async with self._client() as client:
            initialized = await client.post(
                f"{API_BASE}/rest/images?action=initializeUpload",
                json={"initializeUploadRequest": {"owner": owner}},
                headers=self._headers(token),
            )
            if initialized.is_error:
                raise self._error(initialized, "start the image upload")
            try:
                value = initialized.json().get("value") or {}
            except ValueError as exc:
                raise PublishError(
                    "LinkedIn returned an unreadable upload response.", code="transient"
                ) from exc

            upload_url = value.get("uploadUrl")
            image_urn = value.get("image")
            if not upload_url or not image_urn:
                raise PublishError(
                    "LinkedIn did not return an image upload target.", code="transient"
                )

            uploaded = await client.put(
                str(upload_url),
                content=image,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "image/jpeg",
                },
            )
        if uploaded.is_error:
            raise self._error(uploaded, "upload the image")
        return str(image_urn)

    def _error(self, response: httpx.Response, stage: str) -> PublishError:
        """Map an HTTP status onto the codes the UI reacts to."""
        try:
            payload = response.json()
            detail = payload.get("message") or payload.get("error_description") or ""
        except ValueError:
            detail = ""
        suffix = f" {detail}" if detail else ""

        if response.status_code in (401, 403):
            return PublishError(
                f"LinkedIn rejected the credentials.{suffix} "
                "Reconnect the account in Settings.",
                code="reauth",
            )
        if response.status_code == 429:
            return PublishError(
                f"LinkedIn is rate limiting this app.{suffix} Try again shortly.",
                code="rate_limited",
            )
        if response.status_code >= 500:
            return PublishError(
                f"LinkedIn could not {stage} (HTTP {response.status_code}).{suffix}",
                code="transient",
            )
        return PublishError(
            f"LinkedIn refused to {stage} (HTTP {response.status_code}).{suffix}",
            code="invalid",
        )

    async def verify(self, account) -> None:
        """Confirm the token still works, using whichever scope this app has.

        Member-mode apps hold `openid`/`profile` and can read /userinfo; an
        organization app holds `rw_organization_admin` and can read its ACLs.
        Probing the wrong one would report a healthy token as broken.
        """
        author = str(account.metadata.get("author_urn") or "")
        token = account.access_token
        if author.startswith("urn:li:person:"):
            url = f"{API_BASE}/v2/userinfo"
            params: dict | None = None
        else:
            url = f"{API_BASE}/rest/organizationAcls"
            params = {
                "q": "roleAssignee",
                "role": "ADMINISTRATOR",
                "state": "APPROVED",
            }
        async with self._client() as client:
            response = await client.get(url, params=params, headers=self._headers(token))
        if response.is_error:
            raise self._error(response, "check the connection")
