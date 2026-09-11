"""Post media endpoints: generate, upload, browse the library, choose what goes out.

The upload route is the only place in this application where a caller's bytes
enter and are later served to the public internet, so it is deliberately the
thinnest thing here: read with a cap, hand to the ingest pipeline, translate
its refusal into a 400. Every judgement about the bytes themselves lives in
``app.content.ingest``, where it is pure and testable.
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.content import get_llm
from app.auth.dependencies import get_current_user
from app.auth.rate_limit import get_rate_limiter
from app.config import Settings, get_settings
from app.content.ingest import MediaRejectedError, extension_for
from app.content.media import (
    MediaAssetInUseError,
    MediaAssetNotFoundError,
    MediaSelectionError,
    MediaService,
)
from app.content.schemas import (
    GenerateImageRequest,
    ImageSuggestionsResponse,
    ItemMediaOut,
    MediaAssetOut,
    MediaLibraryOut,
    SetSelectionRequest,
    SetSelectionResponse,
)
from app.content.service import ContentItemNotFoundError
from app.db.base import get_session
from app.db.models import ContentItem, ContentItemMedia, MediaAsset, User
from app.llm.client import LLMClient, LLMError
from app.llm.images import ImageGenerationError
from app.publishing.rules import LIMITS

router = APIRouter(
    prefix="/api/content",
    tags=["content-media"],
    dependencies=[Depends(get_current_user)],
)

# Uploads are cheap to send and expensive to process (decode, resize,
# re-encode), so they get their own bucket rather than riding the default.
UPLOAD_RATE_LIMIT = 30
UPLOAD_RATE_WINDOW_SECONDS = 60


def get_media_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    llm: LLMClient = Depends(get_llm),
) -> MediaService:
    return MediaService(session, llm, settings)


def _asset_out(asset: MediaAsset) -> MediaAssetOut:
    return MediaAssetOut(
        id=str(asset.id),
        source=asset.source.value,
        prompt=asset.prompt,
        model=asset.model,
        filename=asset.filename,
        mime_type=asset.mime_type,
        width=asset.width,
        height=asset.height,
        byte_size=asset.byte_size,
        alt_text=asset.alt_text,
        created_at=asset.created_at,
        file_url=f"/api/content/images/{asset.id}/file",
    )


def _selection_out(row: ContentItemMedia) -> ItemMediaOut:
    return ItemMediaOut(
        media_asset_id=str(row.media_asset_id),
        position=row.position,
        alt_text=row.alt_text,
    )


_NOT_FOUND = status.HTTP_404_NOT_FOUND
# 503, not 502: a 502 is what the production host answers when it kills a
# request, and an AI failure must not look like the server falling over.
_AI_UNAVAILABLE = status.HTTP_503_SERVICE_UNAVAILABLE
SUGGESTIONS_UNAVAILABLE_DETAIL = (
    "The AI could not suggest image prompts right now. Please try again in a minute."
)


# ── generate ──


@router.post("/{item_id}/images/suggestions", response_model=ImageSuggestionsResponse)
async def suggest_image_prompts(
    item_id: uuid.UUID,
    service: MediaService = Depends(get_media_service),
) -> ImageSuggestionsResponse:
    try:
        prompts = await service.suggest_prompts(item_id)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(
            status_code=_AI_UNAVAILABLE, detail=SUGGESTIONS_UNAVAILABLE_DETAIL
        ) from exc
    return ImageSuggestionsResponse(prompts=prompts)


@router.post("/{item_id}/images", response_model=MediaAssetOut)
async def generate_image(
    item_id: uuid.UUID,
    body: GenerateImageRequest,
    service: MediaService = Depends(get_media_service),
    user: User = Depends(get_current_user),
) -> MediaAssetOut:
    try:
        asset = await service.generate(
            item_id, prompt=body.prompt, actor_id=user.id, quality=body.quality
        )
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc
    except ImageGenerationError as exc:
        # The message is written for the person (see app.llm.images), and a
        # configuration problem names the setting to fix, so it goes out as-is.
        raise HTTPException(status_code=_AI_UNAVAILABLE, detail=str(exc)) from exc
    return _asset_out(asset)


# ── upload ──


async def _read_capped(upload: UploadFile, limit: int) -> bytes:
    """Read the body, stopping one byte past the limit.

    The ``Content-Length`` header is a claim; this is the fact. Reading one
    extra byte is what lets the caller be told the file is too large without
    ever holding an unbounded amount of it in memory.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise MediaRejectedError(
                f"That file is larger than the {limit // (1024 * 1024)} MB limit."
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/{item_id}/media", response_model=list[MediaAssetOut])
async def upload_media(
    item_id: uuid.UUID,
    request: Request,
    files: list[UploadFile] = File(...),
    service: MediaService = Depends(get_media_service),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> list[MediaAssetOut]:
    limiter = get_rate_limiter()
    client_host = request.client.host if request.client else "unknown"
    if not limiter.check(
        f"media-upload:{client_host}",
        max_hits=UPLOAD_RATE_LIMIT,
        window_seconds=UPLOAD_RATE_WINDOW_SECONDS,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many uploads. Wait a moment and try again.",
        )

    # Declared length is checked first so an obviously oversized body is
    # refused before a byte of it is read.
    declared = request.headers.get("content-length")
    if declared and declared.isdigit():
        # The multipart envelope adds a little, so this is a coarse gate; the
        # per-file cap in `_read_capped` is the real one.
        if int(declared) > settings.media_upload_max_bytes * len(files) + 1_048_576:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="That upload is larger than the limit.",
            )

    assets: list[MediaAsset] = []
    try:
        for upload in files:
            data = await _read_capped(upload, settings.media_upload_max_bytes)
            assets.append(
                await service.upload(
                    item_id,
                    data=data,
                    filename=upload.filename,
                    actor_id=user.id,
                )
            )
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc
    except MediaRejectedError as exc:
        # Named per file by the service, so the operator knows which one to fix.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return [_asset_out(asset) for asset in assets]


# ── library and selection ──


@router.get("/{item_id}/media", response_model=MediaLibraryOut)
async def get_media(
    item_id: uuid.UUID,
    service: MediaService = Depends(get_media_service),
    session: AsyncSession = Depends(get_session),
) -> MediaLibraryOut:
    try:
        library = await service.library(item_id)
        selection = await service.selection(item_id)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc
    item = await session.get(ContentItem, item_id)
    assert item is not None  # service.library already 404s on a missing item
    return MediaLibraryOut(
        library=[_asset_out(asset) for asset in library],
        selection=[_selection_out(row) for row in selection],
        max_images=LIMITS[item.platform].max_images,
    )


@router.put("/{item_id}/media/selection", response_model=SetSelectionResponse)
async def set_media_selection(
    item_id: uuid.UUID,
    body: SetSelectionRequest,
    service: MediaService = Depends(get_media_service),
    user: User = Depends(get_current_user),
) -> SetSelectionResponse:
    try:
        result = await service.set_selection(
            item_id,
            asset_ids=body.asset_ids,
            actor_id=user.id,
            apply_to_group=body.apply_to_group,
        )
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc
    except MediaSelectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return SetSelectionResponse(
        selection=[_selection_out(row) for row in result.selection],
        warnings=result.warnings,
    )


@router.get("/{item_id}/images", response_model=list[MediaAssetOut])
async def list_images(
    item_id: uuid.UUID,
    service: MediaService = Depends(get_media_service),
) -> list[MediaAssetOut]:
    """The library, flat. Kept because callers that only need the pictures
    should not have to know about selection."""
    try:
        assets = await service.library(item_id)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc
    return [_asset_out(asset) for asset in assets]


# ── one asset ──


@router.delete("/media/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    asset_id: uuid.UUID,
    service: MediaService = Depends(get_media_service),
    user: User = Depends(get_current_user),
) -> Response:
    try:
        await service.delete_asset(asset_id, actor_id=user.id)
    except MediaAssetNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc
    except MediaAssetInUseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/images/{image_id}/file")
async def image_file(
    image_id: uuid.UUID,
    download: bool = False,
    service: MediaService = Depends(get_media_service),
) -> Response:
    try:
        asset = await service.get_asset(image_id)
    except MediaAssetNotFoundError as exc:
        raise HTTPException(status_code=_NOT_FOUND, detail=str(exc)) from exc

    # nosniff because these bytes are no longer all PNGs of our own making:
    # an uploaded file must be rendered as the type we decided it is, never as
    # whatever a browser guesses from the content.
    headers = {"X-Content-Type-Options": "nosniff"}
    if download:
        # Named from the asset id, never from the caller-supplied filename.
        extension = extension_for(asset.mime_type)
        headers["Content-Disposition"] = (
            f'attachment; filename="wrcc-post-image-{asset.id.hex[:8]}.{extension}"'
        )
    return Response(content=asset.data, media_type=asset.mime_type, headers=headers)
