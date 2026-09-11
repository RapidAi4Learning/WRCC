"""Content generation + history + workflow endpoints (plan §7)."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.content.repository import ContentRepository
from app.content.schemas import (
    ContentItemOut,
    EditContentRequest,
    GenerateContentRequest,
    GenerateContentResponse,
    RegenerateContentRequest,
    RejectContentRequest,
)
from app.content.service import (
    ContentGenerationService,
    ContentItemNotFoundError,
    ContentWorkflowService,
    CourseNotFoundError,
    GenerationTimeoutError,
)
from app.content.state import ContentTransitionError
from app.db.base import get_session
from app.db.enums import ContentPlatform, ContentStatus
from app.db.models import ContentItem, User
from app.llm.client import LLMClient, LLMError, get_llm_client

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/content", tags=["content"], dependencies=[Depends(get_current_user)]
)

# Shown to the person as-is by the frontend. Always 503, never 502: a 502 is
# what the production host answers when it kills a request, and "the AI failed"
# must not be mistaken for "the server fell over".
AI_UNAVAILABLE_DETAIL = (
    "The AI could not write the posts right now. Please try again in a minute."
)
AI_TIMEOUT_DETAIL = (
    "The AI took too long to answer. Try again, or generate for fewer platforms."
)


def _ai_failure(exc: LLMError | GenerationTimeoutError) -> HTTPException:
    """The 503 for an AI call that failed or ran past the deadline."""
    # The detail sent to the browser is generic by design; the cause goes to
    # the server log, where it can be read without exposing provider errors.
    logger.warning("AI generation failed: %s", exc)
    detail = (
        AI_TIMEOUT_DETAIL if isinstance(exc, GenerationTimeoutError) else AI_UNAVAILABLE_DETAIL
    )
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail)


def get_llm(settings: Settings = Depends(get_settings)) -> LLMClient:
    return get_llm_client(settings)


def get_workflow(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    llm: LLMClient = Depends(get_llm),
) -> ContentWorkflowService:
    return ContentWorkflowService(session, llm, settings)


def _item_out(item: ContentItem) -> ContentItemOut:
    return ContentItemOut(
        id=str(item.id),
        platform=item.platform.value,
        topic=item.topic,
        reference_url=item.reference_url,
        notes=item.notes,
        course_id=str(item.course_id) if item.course_id else None,
        generation_group=str(item.generation_group) if item.generation_group else None,
        variant_style=item.variant_style,
        generated_body=item.generated_body,
        edited_body=item.edited_body,
        body=item.edited_body or item.generated_body,
        hashtags=list(item.hashtags or []),
        call_to_action=item.call_to_action,
        status=item.status.value,
        ai_metadata=item.ai_metadata,
        created_at=item.created_at,
        updated_at=item.updated_at,
        reviewed_at=item.reviewed_at,
    )


async def _call(method, item_id: uuid.UUID, **kwargs) -> ContentItem:
    """Map service errors to clean HTTP statuses (404 / 409 / 503)."""
    try:
        return await method(item_id, **kwargs)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ContentTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (LLMError, GenerationTimeoutError) as exc:
        raise _ai_failure(exc) from exc


@router.post("/generate", response_model=GenerateContentResponse)
async def generate_content(
    body: GenerateContentRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    llm: LLMClient = Depends(get_llm),
    user: User = Depends(get_current_user),
) -> GenerateContentResponse:
    service = ContentGenerationService(session, llm, settings)
    try:
        group, items, warnings = await service.generate(body, actor_id=user.id)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (LLMError, GenerationTimeoutError) as exc:
        raise _ai_failure(exc) from exc
    return GenerateContentResponse(
        generation_group=str(group),
        items=[_item_out(item) for item in items],
        warnings=warnings,
    )


@router.get("", response_model=list[ContentItemOut])
async def list_content(
    platform: ContentPlatform | None = None,
    status_filter: ContentStatus | None = None,
    course_id: uuid.UUID | None = None,
    generation_group: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ContentItemOut]:
    items = await ContentRepository(session).list_items(
        platform=platform,
        status=status_filter,
        course_id=course_id,
        generation_group=generation_group,
    )
    return [_item_out(item) for item in items]


@router.get("/{item_id}", response_model=ContentItemOut)
async def get_content(
    item_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ContentItemOut:
    item = await ContentRepository(session).get(item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Content item not found."
        )
    return _item_out(item)


@router.put("/{item_id}", response_model=ContentItemOut)
async def edit_content(
    item_id: uuid.UUID,
    body: EditContentRequest,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    return _item_out(
        await _call(workflow.edit, item_id, actor_id=user.id, body=body.body)
    )


@router.post("/{item_id}/submit", response_model=ContentItemOut)
async def submit_content(
    item_id: uuid.UUID,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    return _item_out(await _call(workflow.submit, item_id, actor_id=user.id))


@router.post("/{item_id}/approve", response_model=ContentItemOut)
async def approve_content(
    item_id: uuid.UUID,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    return _item_out(await _call(workflow.approve, item_id, actor_id=user.id))


@router.post("/{item_id}/reject", response_model=ContentItemOut)
async def reject_content(
    item_id: uuid.UUID,
    body: RejectContentRequest | None = None,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    reason = body.reason if body else None
    return _item_out(
        await _call(workflow.reject, item_id, actor_id=user.id, reason=reason)
    )


@router.post("/{item_id}/archive", response_model=ContentItemOut)
async def archive_content(
    item_id: uuid.UUID,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    return _item_out(await _call(workflow.archive, item_id, actor_id=user.id))


@router.post("/{item_id}/restore", response_model=ContentItemOut)
async def restore_content(
    item_id: uuid.UUID,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    return _item_out(await _call(workflow.restore, item_id, actor_id=user.id))


@router.post("/{item_id}/duplicate", response_model=ContentItemOut)
async def duplicate_content(
    item_id: uuid.UUID,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    return _item_out(await _call(workflow.duplicate, item_id, actor_id=user.id))


@router.post("/{item_id}/regenerate", response_model=ContentItemOut)
async def regenerate_content(
    item_id: uuid.UUID,
    body: RegenerateContentRequest | None = None,
    workflow: ContentWorkflowService = Depends(get_workflow),
    user: User = Depends(get_current_user),
) -> ContentItemOut:
    instruction = body.instruction if body else None
    return _item_out(
        await _call(workflow.regenerate, item_id, actor_id=user.id, instruction=instruction)
    )
