"""Post-image endpoints: suggestions, generation, history, file download."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.content import get_llm
from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.content.images import (
    ContentImageNotFoundError,
    ContentImageService,
)
from app.content.schemas import (
    ContentImageOut,
    GenerateImageRequest,
    ImageSuggestionsResponse,
)
from app.content.service import ContentItemNotFoundError
from app.db.base import get_session
from app.db.models import ContentImage, User
from app.llm.client import LLMClient, LLMError
from app.llm.images import ImageGenerationError

router = APIRouter(
    prefix="/api/content",
    tags=["content-images"],
    dependencies=[Depends(get_current_user)],
)


def get_image_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    llm: LLMClient = Depends(get_llm),
) -> ContentImageService:
    return ContentImageService(session, llm, settings)


def _image_out(image: ContentImage) -> ContentImageOut:
    return ContentImageOut(
        id=str(image.id),
        content_item_id=str(image.content_item_id),
        prompt=image.prompt,
        model=image.model,
        created_at=image.created_at,
        file_url=f"/api/content/images/{image.id}/file",
    )


@router.post("/{item_id}/images/suggestions", response_model=ImageSuggestionsResponse)
async def suggest_image_prompts(
    item_id: uuid.UUID,
    service: ContentImageService = Depends(get_image_service),
) -> ImageSuggestionsResponse:
    try:
        prompts = await service.suggest_prompts(item_id)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except LLMError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return ImageSuggestionsResponse(prompts=prompts)


@router.post("/{item_id}/images", response_model=ContentImageOut)
async def generate_image(
    item_id: uuid.UUID,
    body: GenerateImageRequest,
    service: ContentImageService = Depends(get_image_service),
    user: User = Depends(get_current_user),
) -> ContentImageOut:
    try:
        image = await service.generate(item_id, prompt=body.prompt, actor_id=user.id)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImageGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return _image_out(image)


@router.get("/{item_id}/images", response_model=list[ContentImageOut])
async def list_images(
    item_id: uuid.UUID,
    service: ContentImageService = Depends(get_image_service),
) -> list[ContentImageOut]:
    try:
        images = await service.list_images(item_id)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_image_out(image) for image in images]


@router.get("/images/{image_id}/file")
async def image_file(
    image_id: uuid.UUID,
    download: bool = False,
    service: ContentImageService = Depends(get_image_service),
) -> Response:
    try:
        image = await service.get_image(image_id)
    except ContentImageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    # Content-Disposition: attachment triggers a browser download; without it
    # the image renders inline in <img> tags.
    headers = (
        {
            "Content-Disposition": (
                f'attachment; filename="wrcc-post-image-{image.id.hex[:8]}.png"'
            )
        }
        if download
        else {}
    )
    return Response(content=image.data, media_type="image/png", headers=headers)
