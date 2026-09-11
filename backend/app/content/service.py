"""Content generation + HITL workflow services.

Generation flow (plan §5): resolve course facts → best-effort reference fetch
→ 3 ranked variants per platform → persist as draft items sharing one
``generation_group`` + audit row. Workflow transitions go through
``assert_transition`` and always write audit rows.

Every platform and variant is requested at once, and the whole of it runs
under ``GENERATION_DEADLINE_SECONDS`` — below the ~120 s after which the
production host kills the request with a 502. Nothing is written until every
call has returned, so hitting the deadline leaves nothing half-saved
(docs/GENERATION-LATENCY-PLAN.md).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.content_generator import (
    GeneratedDraft,
    run_all,
    run_content_generator_variants,
)
from app.audit import record_audit
from app.config import Settings
from app.content.repository import ContentRepository
from app.content.schemas import GenerateContentRequest
from app.content.state import assert_transition
from app.db.enums import ContentStatus
from app.db.models import ContentItem, Course
from app.llm.client import LLMClient
from app.scraper.repository import CatalogRepository

logger = logging.getLogger(__name__)

UPCOMING_OFFERINGS_IN_CONTEXT = 3

T = TypeVar("T")


class CourseNotFoundError(LookupError):
    pass


class ContentItemNotFoundError(LookupError):
    pass


class GenerationTimeoutError(TimeoutError):
    """A generation or regeneration ran past GENERATION_DEADLINE_SECONDS."""


async def run_within_deadline(work: Coroutine[Any, Any, T], seconds: float) -> T:
    """Await ``work``, cancelling it once ``seconds`` have passed.

    Only the deadline itself becomes ``GenerationTimeoutError``: a
    ``TimeoutError`` raised from inside ``work`` propagates as it was.
    """
    deadline = asyncio.timeout(seconds)
    try:
        async with deadline:
            return await work
    except TimeoutError as exc:
        if deadline.expired():
            raise GenerationTimeoutError(
                f"Generation did not finish within {seconds:g} s."
            ) from exc
        raise


async def fetch_reference_excerpt(
    url: str, settings: Settings
) -> tuple[str | None, str | None]:
    """Best-effort text extraction from a reference URL → (excerpt, warning).

    A hostile or down reference URL must never block generation: any failure
    degrades to a warning recorded in ``ai_metadata``.
    """
    try:
        async with httpx.AsyncClient(
            timeout=settings.reference_fetch_timeout_seconds,
            headers={"User-Agent": settings.scraper_user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = " ".join(soup.get_text(" ", strip=True).split())
        if not text:
            return None, f"reference URL yielded no text: {url}"
        return text[: settings.reference_fetch_max_chars], None
    except Exception as exc:  # noqa: BLE001 - best-effort by contract
        logger.warning("Reference fetch failed for %s: %s", url, exc)
        return None, f"reference URL could not be fetched: {url}"


def build_course_facts(course: Course, offerings: list) -> dict:
    """Real catalog facts injected into the prompt context (requirement 5)."""
    upcoming = []
    for offering in offerings[:UPCOMING_OFFERINGS_IN_CONTEXT]:
        upcoming.append(
            {
                "start_date": offering.start_date.isoformat()
                if offering.start_date
                else None,
                "location": offering.location,
                "places_available": offering.places_available,
                "price": float(offering.price) if offering.price is not None else None,
                "time_text": offering.time_text,
            }
        )
    first = offerings[0] if offerings else None
    return {
        "title": course.title,
        "course_code": course.course_code,
        "category": course.category,
        "description": (course.description or "")[:600] or None,
        "is_accredited": course.is_accredited,
        "price": float(first.price) if first is not None and first.price is not None else None,
        "enrollment_url": first.enrollment_url if first is not None else course.source_url,
        "upcoming_offerings": upcoming,
    }


class ContentGenerationService:
    def __init__(
        self, session: AsyncSession, llm: LLMClient, settings: Settings
    ) -> None:
        self._session = session
        self._llm = llm
        self._settings = settings
        self._repo = ContentRepository(session)
        self._catalog = CatalogRepository(session)

    async def generate(
        self, request: GenerateContentRequest, *, actor_id: uuid.UUID
    ) -> tuple[uuid.UUID, list[ContentItem], list[str]]:
        warnings: list[str] = []
        started = time.perf_counter()

        course_facts: dict | None = None
        if request.course_id is not None:
            course = await self._catalog.get_course(request.course_id)
            if course is None:
                raise CourseNotFoundError(f"Course {request.course_id} not found.")
            offerings = await self._catalog.get_offerings(course.id)
            course_facts = build_course_facts(course, offerings)

        # One semaphore for the whole generation, so LLM_MAX_CONCURRENCY caps
        # the calls across every platform, not per platform.
        semaphore = asyncio.Semaphore(self._settings.llm_max_concurrency)

        # The speed chosen on the Generate screen, else the server's setting.
        llm = (
            self._llm.with_reasoning_effort(request.reasoning_effort)
            if request.reasoning_effort
            else self._llm
        )
        effective_effort = (
            request.reasoning_effort or self._settings.openai_reasoning_effort or None
        )

        async def draft_everything() -> list[list[GeneratedDraft]]:
            reference_excerpt: str | None = None
            if request.reference_url:
                reference_excerpt, warning = await fetch_reference_excerpt(
                    request.reference_url, self._settings
                )
                if warning:
                    warnings.append(warning)
            return await run_all(
                run_content_generator_variants(
                    llm=llm,
                    platform=platform,
                    topic=request.topic,
                    notes=request.notes,
                    course_facts=course_facts,
                    reference_excerpt=reference_excerpt,
                    semaphore=semaphore,
                )
                for platform in request.platforms
            )

        drafts_by_platform = await run_within_deadline(
            draft_everything(), self._settings.generation_deadline_seconds
        )

        generation_group = uuid.uuid4()
        items: list[ContentItem] = []
        generated_at = dt.datetime.now(dt.UTC).isoformat()

        for platform, drafts in zip(request.platforms, drafts_by_platform, strict=True):
            for draft in drafts:
                items.append(
                    self._repo.add(
                        ContentItem(
                            platform=platform,
                            topic=request.topic,
                            reference_url=request.reference_url,
                            notes=request.notes,
                            course_id=request.course_id,
                            generation_group=generation_group,
                            variant_style=draft.style,
                            generated_body=draft.body,
                            hashtags=draft.hashtags,
                            call_to_action=draft.call_to_action,
                            status=ContentStatus.draft,
                            ai_metadata={
                                "mock": self._settings.llm_mock,
                                "model": (
                                    "mock"
                                    if self._settings.llm_mock
                                    else self._settings.live_model_name
                                ),
                                "generated_at": generated_at,
                                "violation_count": draft.violation_count,
                                "context": draft.context,
                                # Which speed wrote it, so copy quality can
                                # later be compared by effort.
                                "reasoning_effort": effective_effort,
                                "warnings": warnings,
                            },
                            created_by=actor_id,
                        )
                    )
                )

        await self._session.flush()
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_generated",
            entity_type="generation_group",
            entity_id=generation_group,
            payload_diff={
                "platforms": [platform.value for platform in request.platforms],
                "course_id": str(request.course_id) if request.course_id else None,
                "topic": request.topic,
                "items": len(items),
            },
        )
        await self._session.commit()
        # One line per generation, readable in the host's stderr.log: the first
        # place to look if generations slow down again.
        logger.info(
            "Generated %d posts for %s in %.1f s (model=%s, reasoning_effort=%s)",
            len(items),
            ",".join(platform.value for platform in request.platforms),
            time.perf_counter() - started,
            "mock" if self._settings.llm_mock else self._settings.live_model_name,
            effective_effort or "-",
        )
        return generation_group, items, warnings


class ContentWorkflowService:
    """HITL workflow over persisted items (submit/approve/reject/…)."""

    def __init__(
        self, session: AsyncSession, llm: LLMClient, settings: Settings
    ) -> None:
        self._session = session
        self._llm = llm
        self._settings = settings
        self._repo = ContentRepository(session)

    async def _get(self, item_id: uuid.UUID) -> ContentItem:
        item = await self._repo.get(item_id)
        if item is None:
            raise ContentItemNotFoundError(f"Content item {item_id} not found.")
        return item

    async def _transition(
        self,
        item_id: uuid.UUID,
        target: ContentStatus,
        *,
        actor_id: uuid.UUID,
        action: str,
        payload: dict | None = None,
        set_reviewer: bool = False,
    ) -> ContentItem:
        item = await self._get(item_id)
        assert_transition(item.status, target)
        payload_diff = {
            "from": item.status.value,
            "to": target.value,
            **(payload or {}),
        }
        item.status = target
        if set_reviewer:
            item.reviewed_by = actor_id
            item.reviewed_at = dt.datetime.now(dt.UTC)
        record_audit(
            self._session,
            actor_id=actor_id,
            action=action,
            entity_type="content_item",
            entity_id=item.id,
            payload_diff=payload_diff,
        )
        await self._session.commit()
        return item

    async def submit(self, item_id: uuid.UUID, *, actor_id: uuid.UUID) -> ContentItem:
        return await self._transition(
            item_id,
            ContentStatus.pending_approval,
            actor_id=actor_id,
            action="content_submitted",
        )

    async def approve(self, item_id: uuid.UUID, *, actor_id: uuid.UUID) -> ContentItem:
        return await self._transition(
            item_id,
            ContentStatus.approved,
            actor_id=actor_id,
            action="content_approved",
            set_reviewer=True,
        )

    async def reject(
        self, item_id: uuid.UUID, *, actor_id: uuid.UUID, reason: str | None = None
    ) -> ContentItem:
        return await self._transition(
            item_id,
            ContentStatus.rejected,
            actor_id=actor_id,
            action="content_rejected",
            payload={"reason": reason} if reason else None,
            set_reviewer=True,
        )

    async def archive(self, item_id: uuid.UUID, *, actor_id: uuid.UUID) -> ContentItem:
        return await self._transition(
            item_id,
            ContentStatus.archived,
            actor_id=actor_id,
            action="content_archived",
        )

    async def restore(self, item_id: uuid.UUID, *, actor_id: uuid.UUID) -> ContentItem:
        return await self._transition(
            item_id,
            ContentStatus.draft,
            actor_id=actor_id,
            action="content_restored",
        )

    async def edit(
        self, item_id: uuid.UUID, *, actor_id: uuid.UUID, body: str
    ) -> ContentItem:
        """Manual edit stores ``edited_body`` and reopens the review cycle."""
        item = await self._get(item_id)
        if item.status != ContentStatus.draft:
            assert_transition(item.status, ContentStatus.draft)
        previous = item.edited_body or item.generated_body
        item.edited_body = body
        item.status = ContentStatus.draft
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_edited",
            entity_type="content_item",
            entity_id=item.id,
            payload_diff={"from_body": previous[:200], "to_body": body[:200]},
        )
        await self._session.commit()
        return item

    async def duplicate(
        self, item_id: uuid.UUID, *, actor_id: uuid.UUID
    ) -> ContentItem:
        """Copy an item back to draft for reuse (history requirement)."""
        source = await self._get(item_id)
        copy = ContentItem(
            platform=source.platform,
            topic=source.topic,
            reference_url=source.reference_url,
            notes=source.notes,
            course_id=source.course_id,
            generation_group=source.generation_group,
            variant_style=source.variant_style,
            generated_body=source.edited_body or source.generated_body,
            hashtags=list(source.hashtags or []),
            call_to_action=source.call_to_action,
            status=ContentStatus.draft,
            ai_metadata={
                **(source.ai_metadata or {}),
                "duplicated_from": str(source.id),
            },
            created_by=actor_id,
        )
        self._repo.add(copy)
        await self._session.flush()
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_duplicated",
            entity_type="content_item",
            entity_id=copy.id,
            payload_diff={"source_id": str(source.id)},
        )
        await self._session.commit()
        return copy

    async def regenerate(
        self,
        item_id: uuid.UUID,
        *,
        actor_id: uuid.UUID,
        instruction: str | None = None,
    ) -> ContentItem:
        """Guided regeneration: a fresh draft revising this item's body."""
        source = await self._get(item_id)
        drafts = await run_within_deadline(
            run_content_generator_variants(
                llm=self._llm,
                platform=source.platform,
                topic=source.topic,
                notes=source.notes,
                course_facts=(source.ai_metadata or {}).get("context", {}).get("course"),
                instruction=instruction,
                prior_body=source.edited_body or source.generated_body,
                count=1,
            ),
            self._settings.generation_deadline_seconds,
        )
        draft = drafts[0]
        item = ContentItem(
            platform=source.platform,
            topic=source.topic,
            reference_url=source.reference_url,
            notes=source.notes,
            course_id=source.course_id,
            generation_group=source.generation_group,
            variant_style=draft.style,
            generated_body=draft.body,
            hashtags=draft.hashtags,
            call_to_action=draft.call_to_action,
            status=ContentStatus.draft,
            ai_metadata={
                "mock": self._settings.llm_mock,
                "model": "mock" if self._settings.llm_mock else self._settings.live_model_name,
                "generated_at": dt.datetime.now(dt.UTC).isoformat(),
                "violation_count": draft.violation_count,
                "context": draft.context,
                "regenerated_from": str(source.id),
                "instruction": instruction,
            },
            created_by=actor_id,
        )
        self._repo.add(item)
        await self._session.flush()
        record_audit(
            self._session,
            actor_id=actor_id,
            action="content_regenerated",
            entity_type="content_item",
            entity_id=item.id,
            payload_diff={"source_id": str(source.id), "instruction": instruction},
        )
        await self._session.commit()
        return item
