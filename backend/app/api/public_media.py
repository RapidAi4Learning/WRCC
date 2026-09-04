"""Unauthenticated signed image endpoint — the only open surface in the app.

Meta fetches post images from its own servers and cannot present a session
cookie, so this endpoint has no auth dependency. Everything that protects it is
in the URL: an HMAC over ``image_id|exp`` with a short TTL.

Two deliberate choices:

* **The signature is checked before the database is touched.** An attacker
  without a valid signature causes zero query load, so this cannot be used to
  probe for image ids or hammer the pool.
* **Every failure is a 404, never a 403.** A 403 would confirm that an image id
  exists, turning the endpoint into an enumeration oracle. Bad signature,
  expired URL, and missing row are indistinguishable from outside.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.base import get_session
from app.db.models import MediaAsset
from app.publishing.media import MediaConversionError, to_jpeg, verify_image_signature

router = APIRouter(tags=["public-media"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


@router.get("/api/public/images/{image_id}.jpg")
async def public_image(
    image_id: uuid.UUID,
    exp: int,
    sig: str,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    if not verify_image_signature(
        settings, image_id=image_id, expires_at=exp, signature=sig
    ):
        raise _NOT_FOUND

    image = await session.get(MediaAsset, image_id)
    if image is None:
        raise _NOT_FOUND

    try:
        # Off the event loop: decode + resize + re-encode is CPU-bound, and
        # blocking here would stall every other request while Meta fetches an
        # image. Cheap to move, since the conversion is pure.
        jpeg = await asyncio.to_thread(to_jpeg, image.data)
    except MediaConversionError as exc:
        # The row exists but its bytes are unusable — that is our problem, not a
        # malformed request, and it should show up in logs as a server fault.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={
            # private: this URL is meant for one fetcher for a few minutes, not
            # for a shared cache to hold on to.
            "Cache-Control": f"private, max-age={settings.media_url_ttl_seconds}",
            "X-Content-Type-Options": "nosniff",
        },
    )
