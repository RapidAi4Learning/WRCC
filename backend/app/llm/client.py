"""LLM client protocol + mock and live (Gemini) implementations.

The agents depend only on the ``LLMClient`` protocol so they are testable
offline. ``MockLLMClient`` is deterministic and respects the platform profile
in the context (length bounds, hashtag counts, CTA), enabling offline demos
and stable tests (D3: mock-first, LLM_MOCK=true by default).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Protocol

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5


class LLMError(RuntimeError):
    """Raised when the LLM cannot produce a valid response after retries."""


class SocialPostDraft(BaseModel):
    """Structured social post returned by every client implementation."""

    body: str
    hashtags: list[str] = Field(default_factory=list)
    call_to_action: str | None = None


class LLMClient(Protocol):
    async def generate_social_post(self, context: dict) -> SocialPostDraft: ...


_WORD_RE = re.compile(r"[A-Za-z]{3,}")

# Deterministic per-style openers so ranked variants differ offline.
_STYLE_OPENERS = {
    "direct": "Enrol now: {subject}.",
    "story_led": "Last month a local student finished {subject} — and walked "
    "straight into new opportunities.",
    "question_led": "Ready to take the next step with {subject}?",
}

_PLATFORM_FLAVOUR = {
    "linkedin": "Nationally recognised training that employers across the "
    "Riverina trust. Build practical, job-ready skills with local trainers.",
    "facebook": "Friendly local trainers, small classes and a supportive "
    "community feel.",
    "instagram": "📚✨ Local learning, real skills!",
}

_PADDING = (
    " Western Riverina Community College supports learners of all backgrounds "
    "with flexible class times and experienced local trainers."
)


def _hashtagify(text: str) -> str:
    return "#" + "".join(word.capitalize() for word in _WORD_RE.findall(text))[:28]


class MockLLMClient:
    """Deterministic offline LLM used when LLM_MOCK is enabled."""

    async def generate_social_post(self, context: dict) -> SocialPostDraft:
        course = context.get("course") or {}
        profile = context.get("platform_profile") or {}
        platform = str(context.get("platform") or "facebook")
        style = str(context.get("variant_style") or "direct")

        subject = course.get("title") or context.get("topic") or "our courses"
        opener = _STYLE_OPENERS.get(style, _STYLE_OPENERS["direct"]).format(
            subject=subject
        )

        parts = [opener]
        if context.get("instruction"):
            # Guided regeneration: surface the instruction so the revision is
            # visibly different offline.
            parts.append(f"({context['instruction']})")
        if context.get("notes"):
            parts.append(str(context["notes"]))
        offerings = course.get("upcoming_offerings") or []
        if offerings:
            first = offerings[0]
            when = first.get("start_date") or "on demand"
            where = first.get("location") or "the Riverina"
            parts.append(f"Next intake: {when} at {where}.")
            if first.get("price") is not None:
                parts.append(f"Course fee: ${first['price']:.0f}.")
        if context.get("reference_excerpt"):
            parts.append("More details on our website.")
        parts.append(_PLATFORM_FLAVOUR.get(platform, ""))

        body = " ".join(part for part in parts if part).strip()

        min_length = int(profile.get("min_length") or 0)
        max_length = int(profile.get("max_length") or 2000)
        while len(body) < min_length:
            body += _PADDING
        if len(body) > max_length:
            body = body[: max_length - 1].rstrip() + "…"

        hashtag_count = int(profile.get("hashtags_min") or 2)
        seeds = [
            "WRCC",
            subject,
            course.get("category") or "Community Learning",
            "Riverina",
            "Learn Local",
            "New Skills",
            "Adult Education",
            "Griffith",
            "Leeton",
            "Deniliquin",
            "Career Boost",
            "Study Local",
            "Training",
            "Enrol Now",
            "Community College",
        ]
        hashtags: list[str] = []
        for seed in seeds:
            tag = _hashtagify(seed)
            if tag not in hashtags:
                hashtags.append(tag)
            if len(hashtags) >= hashtag_count:
                break

        cta_template = str(profile.get("cta") or "Enrol today.")
        enrol_url = course.get("enrollment_url")
        call_to_action = f"{cta_template} {enrol_url}".strip() if enrol_url else cta_template

        return SocialPostDraft(
            body=body, hashtags=hashtags, call_to_action=call_to_action
        )


def _render_prompt(context: dict) -> str:
    """Render the shared generation context as the live-model prompt."""
    profile = context.get("platform_profile") or {}
    lines = [
        "You are the social media copywriter for Western Riverina Community "
        "College (WRCC), a community college in the NSW Riverina.",
        f"Write ONE {context.get('platform')} post.",
        f"Angle for this variant: {context.get('variant_style')}.",
        f"Tone: {profile.get('tone')}.",
        f"Structure: {profile.get('structure')}.",
        f"Body length: between {profile.get('min_length')} and "
        f"{profile.get('max_length')} characters.",
        f"Hashtags: between {profile.get('hashtags_min')} and "
        f"{profile.get('hashtags_max')}.",
        f"Call to action style: {profile.get('cta')}",
    ]
    if context.get("topic"):
        lines.append(f"Topic: {context['topic']}")
    if context.get("notes"):
        lines.append(f"Extra notes from the marketer: {context['notes']}")
    if context.get("course"):
        lines.append(f"Ground the post in this real course data: {context['course']}")
    if context.get("reference_excerpt"):
        lines.append(
            "Reference material (extracted from the provided URL): "
            f"{context['reference_excerpt']}"
        )
    if context.get("prior_body"):
        lines.append(f"Revise this prior draft: {context['prior_body']}")
    if context.get("instruction"):
        lines.append(f"Revision instruction: {context['instruction']}")
    lines.append(
        "Never invent prices, dates or accreditation claims — only use the "
        "course data provided."
    )
    return "\n".join(lines)


class GeminiLLMClient:
    """Live Gemini client (used when LLM_MOCK=false)."""

    def __init__(self, settings: Settings) -> None:
        from google import genai

        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def generate_social_post(self, context: dict) -> SocialPostDraft:
        prompt = _render_prompt(context)
        last_error: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json",
                        "response_schema": SocialPostDraft,
                    },
                )
                return SocialPostDraft.model_validate_json(response.text)
            except (ValidationError, Exception) as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "Gemini attempt %d/%d failed: %s", attempt, _RETRY_ATTEMPTS, exc
                )
                if attempt < _RETRY_ATTEMPTS:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
        raise LLMError("AI generation failed after retries.") from last_error


def get_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_mock:
        return MockLLMClient()
    return GeminiLLMClient(settings)
