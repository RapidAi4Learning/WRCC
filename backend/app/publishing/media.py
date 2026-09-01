"""Signed public image URLs, and the PNG → JPEG conversion behind them.

Two things the networks force on us:

*Signed URLs.* Meta fetches post images from its own servers, so it cannot
present our session cookie: the image endpoint must be unauthenticated. Instead
of leaving it open, each URL carries an HMAC over ``image_id|exp`` and expires
in minutes. The URL is bearer-style for its lifetime — anyone holding it can
fetch the image. That is accepted deliberately: the image is about to be posted
publicly. What the signature buys is that the endpoint cannot be walked or
enumerated.

*JPEG.* Instagram's Content Publishing API rejects PNG outright, and we store
PNG. Conversion happens at serve time; the stored bytes stay canonical, so
nothing about the existing image feature changes.

Pure functions; the endpoint that serves the bytes lives in
``app.api.public_media``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import io
import uuid

from PIL import Image, UnidentifiedImageError

from app.config import Settings

JPEG_QUALITY = 88

# Instagram's documented feed-image spec. Width and format we fix ourselves at
# serve time; aspect ratio we cannot fix without cropping someone's image, so
# that one is reported to the operator instead.
INSTAGRAM_MAX_WIDTH = 1440
INSTAGRAM_MIN_WIDTH = 320
INSTAGRAM_MIN_ASPECT = 0.8  # 4:5 portrait
INSTAGRAM_MAX_ASPECT = 1.91  # 1.91:1 landscape


class MediaSigningError(RuntimeError):
    """Raised when a signed media URL cannot be built (missing configuration)."""


class MediaConversionError(RuntimeError):
    """Raised when stored bytes are not a readable image."""


def _open(data: bytes) -> Image.Image:
    try:
        return Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise MediaConversionError("Stored image data is not a readable image.") from exc


def image_size(data: bytes) -> tuple[int, int]:
    """(width, height) without decoding the pixels — PIL reads the header only."""
    with _open(data) as image:
        return image.size


def to_jpeg(
    data: bytes,
    *,
    quality: int = JPEG_QUALITY,
    max_width: int | None = INSTAGRAM_MAX_WIDTH,
) -> bytes:
    """Convert stored bytes to a JPEG within the networks' limits.

    Transparency is flattened onto white rather than the black that a naive
    ``convert("RGB")`` produces: these are social images, and a logo on a
    transparent background would otherwise arrive as a dark smear.
    """
    with _open(data) as image:
        if image.mode in ("RGBA", "LA", "P"):
            rgba = image.convert("RGBA")
            flattened = Image.new("RGB", rgba.size, (255, 255, 255))
            flattened.paste(rgba, mask=rgba.split()[-1])
            rgb = flattened
        else:
            rgb = image.convert("RGB")

        if max_width is not None and rgb.width > max_width:
            height = round(rgb.height * max_width / rgb.width)
            rgb = rgb.resize((max_width, height), Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()


def instagram_problems(data: bytes) -> list[str]:
    """Spec violations we cannot fix for the operator.

    Oversized width and the PNG format are handled by ``to_jpeg``; what is left
    is an image too small to post or shaped outside Instagram's accepted range.
    """
    try:
        width, height = image_size(data)
    except MediaConversionError as exc:
        return [str(exc)]

    problems: list[str] = []
    # Downscaling to the max width shrinks height too, so check the ratio the
    # served image will actually have.
    effective_width = min(width, INSTAGRAM_MAX_WIDTH)
    if effective_width < INSTAGRAM_MIN_WIDTH:
        problems.append(
            f"The image is {width}px wide; Instagram needs at least "
            f"{INSTAGRAM_MIN_WIDTH}px."
        )
    if height == 0:
        return problems

    aspect = width / height
    if aspect < INSTAGRAM_MIN_ASPECT or aspect > INSTAGRAM_MAX_ASPECT:
        problems.append(
            f"The image is {width}×{height} (ratio {aspect:.2f}); Instagram "
            f"accepts {INSTAGRAM_MIN_ASPECT} to {INSTAGRAM_MAX_ASPECT}."
        )
    return problems


def _signature(secret: str, *, image_id: uuid.UUID, expires_at: int) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{image_id}|{expires_at}".encode(),
        hashlib.sha256,
    ).hexdigest()


def sign_image_url(
    settings: Settings,
    *,
    image_id: uuid.UUID,
    now: dt.datetime | None = None,
) -> str:
    """Build the absolute, signed, short-lived URL Meta will fetch.

    Absolute because the consumer is another company's server: a relative path
    (as used by the authenticated ``/file`` endpoint) is meaningless to it.
    """
    if not settings.media_signing_secret:
        raise MediaSigningError("MEDIA_SIGNING_SECRET is not set.")
    if not settings.media_base_url:
        raise MediaSigningError(
            "Neither PUBLIC_MEDIA_BASE_URL nor PUBLIC_API_BASE_URL is set — the "
            "networks cannot fetch an image from a host they cannot reach."
        )
    now = now or dt.datetime.now(dt.UTC)
    expires_at = int((now + dt.timedelta(seconds=settings.media_url_ttl_seconds)).timestamp())
    signature = _signature(
        settings.media_signing_secret, image_id=image_id, expires_at=expires_at
    )
    base = settings.media_base_url.rstrip("/")
    return f"{base}/api/public/images/{image_id}.jpg?exp={expires_at}&sig={signature}"


def verify_image_signature(
    settings: Settings,
    *,
    image_id: uuid.UUID,
    expires_at: int,
    signature: str,
    now: dt.datetime | None = None,
) -> bool:
    """Constant-time signature check plus expiry. False means: serve a 404."""
    if not settings.media_signing_secret:
        return False
    now = now or dt.datetime.now(dt.UTC)
    if expires_at < int(now.timestamp()):
        return False
    expected = _signature(
        settings.media_signing_secret, image_id=image_id, expires_at=expires_at
    )
    return hmac.compare_digest(expected, signature)
