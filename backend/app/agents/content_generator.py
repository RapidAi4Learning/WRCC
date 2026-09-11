"""Content generator agent node (pure — no DB or framework imports).

Builds a platform- and course-grounded prompt context, calls the shared
``LLMClient`` (mock offline / Gemini live), and returns dependency-free drafts
the service layer persists. Each generation pass takes a distinct angle
(``CONTENT_VARIANT_STYLES``) so the 3 variants per platform genuinely differ,
and results are ranked by the deterministic rule-baseline violation count —
no extra LLM call needed to judge them.

The variants are requested concurrently: each one is an independent call of
tens of seconds, and one after another they ran a generation past the host's
~120 s request limit (docs/GENERATION-LATENCY-PLAN.md).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Iterable
from dataclasses import dataclass
from typing import Any, TypeVar

from app.agents.validation import validate_generated_content
from app.db.enums import ContentPlatform
from app.llm.client import LLMClient

T = TypeVar("T")

CONTENT_VARIANT_STYLES: tuple[str, ...] = ("direct", "story_led", "question_led")
DEFAULT_VARIANT_COUNT = 3

# Per-platform tone/format profile (D4: versioned constants in code, no
# brand-voice table). Injected into the prompt context and enforced by the
# validation baseline.
PLATFORM_PROFILES: dict[str, dict] = {
    ContentPlatform.linkedin.value: {
        "tone": "professional, oriented to career development and employers",
        "min_length": 600,
        "max_length": 1300,
        "hashtags_min": 3,
        "hashtags_max": 5,
        "cta": "Enrol now or upskill your team.",
        "structure": "hook + value + credential (accredited code) + CTA",
    },
    ContentPlatform.facebook.value: {
        "tone": "conversational, community-minded",
        "min_length": 250,
        "max_length": 600,
        "hashtags_min": 2,
        "hashtags_max": 5,
        "cta": "Book your spot.",
        "structure": "hook + benefit + date/location + CTA",
    },
    ContentPlatform.instagram.value: {
        "tone": "visual, energetic, emoji-friendly",
        "min_length": 125,
        "max_length": 400,
        "hashtags_min": 8,
        "hashtags_max": 15,
        "cta": "Link in bio — enrol now.",
        "structure": "short hook + emoji + CTA + hashtag wall",
    },
}


@dataclass(frozen=True, slots=True)
class GeneratedDraft:
    """A generated post variant before it is written to content_items."""

    style: str
    body: str
    hashtags: list[str]
    call_to_action: str | None
    context: dict
    violation_count: int


def build_generation_context(
    *,
    platform: ContentPlatform,
    variant_style: str,
    topic: str | None = None,
    notes: str | None = None,
    course_facts: dict | None = None,
    reference_excerpt: str | None = None,
    instruction: str | None = None,
    prior_body: str | None = None,
) -> dict:
    """Pure assembly of the grounding context handed to the LLM."""
    return {
        "platform": platform.value,
        "platform_profile": PLATFORM_PROFILES[platform.value],
        "variant_style": variant_style,
        "topic": topic or None,
        "notes": notes or None,
        "course": course_facts,
        "reference_excerpt": reference_excerpt or None,
        "instruction": instruction or None,
        "prior_body": prior_body or None,
    }


def _rank_key(draft: GeneratedDraft) -> tuple[int, int]:
    """Fewest rule-baseline violations first, then richer copy."""
    return (draft.violation_count, -len(draft.body))


async def run_all(coroutines: Iterable[Coroutine[Any, Any, T]]) -> list[T]:
    """Run coroutines concurrently; return their results in the given order.

    Unlike ``asyncio.gather``, the first failure cancels the rest instead of
    leaving them running unobserved, and it is re-raised as itself rather than
    wrapped in an ``ExceptionGroup`` — so callers keep catching ``LLMError``.
    """
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(coroutine) for coroutine in coroutines]
    except BaseExceptionGroup as failures:
        raise failures.exceptions[0]  # noqa: B904 - the group is only a wrapper
    return [task.result() for task in tasks]


async def run_content_generator_variants(
    *,
    llm: LLMClient,
    platform: ContentPlatform,
    topic: str | None = None,
    notes: str | None = None,
    course_facts: dict | None = None,
    reference_excerpt: str | None = None,
    instruction: str | None = None,
    prior_body: str | None = None,
    count: int = DEFAULT_VARIANT_COUNT,
    semaphore: asyncio.Semaphore | None = None,
) -> list[GeneratedDraft]:
    """Draft ``count`` ranked variants for one platform (3 ideas per request).

    ``semaphore``, when given, caps how many provider calls are in flight — it
    is shared across platforms by the service so one generation stays within
    ``LLM_MAX_CONCURRENCY``.
    """

    async def draft(style: str) -> GeneratedDraft:
        context = build_generation_context(
            platform=platform,
            variant_style=style,
            topic=topic,
            notes=notes,
            course_facts=course_facts,
            reference_excerpt=reference_excerpt,
            instruction=instruction,
            prior_body=prior_body,
        )
        if semaphore is None:
            post = await llm.generate_social_post(context)
        else:
            async with semaphore:
                post = await llm.generate_social_post(context)
        violations = validate_generated_content(
            platform=platform,
            body=post.body,
            hashtags=list(post.hashtags),
            call_to_action=post.call_to_action,
        )
        return GeneratedDraft(
            style=style,
            body=post.body,
            hashtags=list(post.hashtags),
            call_to_action=post.call_to_action,
            context=context,
            violation_count=len(violations),
        )

    drafts = await run_all(draft(style) for style in CONTENT_VARIANT_STYLES[: max(1, count)])
    return sorted(drafts, key=_rank_key)
