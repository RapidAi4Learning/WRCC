"""JPEG conversion and the unauthenticated signed image endpoint."""

from __future__ import annotations

import datetime as dt
import io
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from PIL import Image

from app.db.enums import ContentPlatform, ContentStatus
from app.db.models import ContentImage, ContentItem
from app.publishing.media import (
    INSTAGRAM_MAX_WIDTH,
    MediaConversionError,
    image_size,
    instagram_problems,
    sign_image_url,
    to_jpeg,
)
from tests.conftest import make_settings

JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png(width: int, height: int, *, mode: str = "RGB", colour=(20, 92, 63)) -> bytes:
    image = Image.new(mode, (width, height), colour if mode == "RGB" else None)
    if mode == "RGBA":
        image = Image.new("RGBA", (width, height), (20, 92, 63, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


# ── conversion ──


def test_png_converts_to_jpeg() -> None:
    jpeg = to_jpeg(_png(800, 800))
    assert jpeg.startswith(JPEG_MAGIC)
    assert not jpeg.startswith(PNG_MAGIC)
    assert image_size(jpeg) == (800, 800)


def test_transparency_is_flattened_onto_white_not_black() -> None:
    # A naive convert("RGB") composites onto black, which turns a logo on a
    # transparent background into a dark smear once posted.
    jpeg = to_jpeg(_png(64, 64, mode="RGBA"))
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.getpixel((32, 32)) == pytest.approx((255, 255, 255), abs=4)


def test_oversized_images_are_downscaled_preserving_aspect() -> None:
    jpeg = to_jpeg(_png(2880, 1440))
    width, height = image_size(jpeg)
    assert width == INSTAGRAM_MAX_WIDTH
    assert height == INSTAGRAM_MAX_WIDTH // 2  # 2:1 preserved


def test_small_images_are_not_upscaled() -> None:
    assert image_size(to_jpeg(_png(400, 400))) == (400, 400)


def test_converted_image_stays_well_under_the_instagram_size_cap() -> None:
    jpeg = to_jpeg(_png(4000, 4000))
    assert len(jpeg) < 8 * 1024 * 1024


def test_unreadable_bytes_raise_a_clear_error() -> None:
    with pytest.raises(MediaConversionError, match="not a readable image"):
        to_jpeg(b"this is not an image")


# ── Instagram spec ──


def test_square_image_passes_the_instagram_spec() -> None:
    assert instagram_problems(_png(1024, 1024)) == []


@pytest.mark.parametrize(
    ("width", "height"),
    [(1000, 1000), (1080, 1350), (1080, 566)],  # square, 4:5, 1.91:1
)
def test_accepted_aspect_ratios(width: int, height: int) -> None:
    assert instagram_problems(_png(width, height)) == []


@pytest.mark.parametrize(
    ("width", "height"),
    [(1000, 2000), (2000, 500)],  # too tall, too wide
)
def test_rejected_aspect_ratios(width: int, height: int) -> None:
    problems = instagram_problems(_png(width, height))
    assert any("ratio" in problem for problem in problems)


def test_image_too_small_is_reported() -> None:
    problems = instagram_problems(_png(200, 200))
    assert any("at least 320px" in problem for problem in problems)


def test_wide_image_is_not_flagged_for_width_since_we_downscale_it() -> None:
    # 2000px wide is over Instagram's max, but to_jpeg fixes that, so it must
    # not surface as a blocker the operator cannot act on.
    assert instagram_problems(_png(2000, 1400)) == []


def test_unreadable_bytes_surface_as_a_problem_not_an_exception() -> None:
    assert instagram_problems(b"nope") == [
        "Stored image data is not a readable image."
    ]


# ── the endpoint ──


async def _store_image(db_sessionmaker, data: bytes) -> uuid.UUID:
    async with db_sessionmaker() as session:
        item = ContentItem(
            platform=ContentPlatform.instagram,
            variant_style="direct",
            generated_body="body",
            status=ContentStatus.approved,
        )
        session.add(item)
        await session.flush()
        image = ContentImage(
            content_item_id=item.id, prompt="a classroom", model="mock", data=data
        )
        session.add(image)
        await session.commit()
        return image.id


def _signed_path(image_id: uuid.UUID, **overrides) -> str:
    url = sign_image_url(make_settings(), image_id=image_id)
    parsed = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    query.update(overrides)
    return f"{parsed.path}?exp={query['exp']}&sig={query['sig']}"


async def test_signed_url_serves_a_jpeg_without_authentication(
    client: AsyncClient, db_sessionmaker
) -> None:
    # Deliberately the unauthenticated `client`, not `auth_client`: Meta fetches
    # this from its own servers with no cookie.
    image_id = await _store_image(db_sessionmaker, _png(1024, 1024))

    response = await client.get(_signed_path(image_id))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content.startswith(JPEG_MAGIC)
    assert response.headers["cache-control"].startswith("private")
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_unsigned_request_is_a_404(client: AsyncClient, db_sessionmaker) -> None:
    image_id = await _store_image(db_sessionmaker, _png(512, 512))
    response = await client.get(f"/api/public/images/{image_id}.jpg")
    assert response.status_code == 422  # exp/sig are required query params


async def test_bad_signature_is_404_not_403(
    client: AsyncClient, db_sessionmaker
) -> None:
    # A 403 would confirm the image exists, turning this into an enumeration
    # oracle. Every failure must look identical from outside.
    image_id = await _store_image(db_sessionmaker, _png(512, 512))

    response = await client.get(_signed_path(image_id, sig="deadbeef"))

    assert response.status_code == 404
    assert response.json()["detail"] == "Not found."


async def test_expired_url_is_404(client: AsyncClient, db_sessionmaker) -> None:
    image_id = await _store_image(db_sessionmaker, _png(512, 512))
    past = int((dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).timestamp())

    response = await client.get(_signed_path(image_id, exp=str(past)))

    assert response.status_code == 404


async def test_extending_the_expiry_does_not_extend_the_url(
    client: AsyncClient, db_sessionmaker
) -> None:
    image_id = await _store_image(db_sessionmaker, _png(512, 512))
    future = int((dt.datetime.now(dt.UTC) + dt.timedelta(days=365)).timestamp())

    response = await client.get(_signed_path(image_id, exp=str(future)))

    assert response.status_code == 404


async def test_unknown_image_is_404_with_the_same_body(client: AsyncClient) -> None:
    response = await client.get(_signed_path(uuid.uuid4()))
    assert response.status_code == 404
    assert response.json()["detail"] == "Not found."


async def test_signature_for_one_image_does_not_serve_another(
    client: AsyncClient, db_sessionmaker
) -> None:
    first = await _store_image(db_sessionmaker, _png(512, 512))
    second = await _store_image(db_sessionmaker, _png(512, 512))
    parsed = urlsplit(sign_image_url(make_settings(), image_id=first))
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    response = await client.get(
        f"/api/public/images/{second}.jpg?exp={query['exp']}&sig={query['sig']}"
    )

    assert response.status_code == 404


async def test_corrupt_stored_bytes_surface_as_a_server_error(
    client: AsyncClient, db_sessionmaker
) -> None:
    # 500, not 404: the URL was valid and the row exists. Hiding a corrupt
    # image behind "Not found." would send someone hunting the wrong problem.
    image_id = await _store_image(db_sessionmaker, b"not an image at all")

    response = await client.get(_signed_path(image_id))

    assert response.status_code == 500
    assert "not a readable image" in response.json()["detail"]
