"""LLM client protocol + mock and live (Gemini / OpenAI) implementations.

The agents depend only on the ``LLMClient`` protocol so they are testable
offline. ``MockLLMClient`` is deterministic and respects the platform profile
in the context (length bounds, hashtag counts, CTA), enabling offline demos
and stable tests (D3: mock-first, LLM_MOCK=true by default).
"""

from __future__ import annotations

import asyncio
import copy
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, Field

from app.config import Settings

logger = logging.getLogger(__name__)

# Ours is the only retry layer: the SDKs' own retries are switched off, so the
# two cannot multiply. Live clients pass Settings.llm_max_attempts.
DEFAULT_ATTEMPTS = 2
_RETRY_BACKOFF_SECONDS = 0.5

# OpenAI model families that accept `reasoning_effort`. Every other model
# answers 400 "Unsupported parameter", so the effort is only sent to these.
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def supports_reasoning_effort(model: str) -> bool:
    return model.startswith(_REASONING_MODEL_PREFIXES)


class LLMError(RuntimeError):
    """Raised when the LLM cannot produce a valid response after retries."""


class SocialPostDraft(BaseModel):
    """Structured social post returned by every client implementation."""

    body: str
    hashtags: list[str] = Field(default_factory=list)
    call_to_action: str | None = None


class ImagePromptIdeas(BaseModel):
    """Prompt suggestions for the image generator, one post at a time."""

    prompts: list[str] = Field(min_length=1)


IMAGE_SUGGESTION_COUNT = 3


class LLMClient(Protocol):
    async def generate_social_post(self, context: dict) -> SocialPostDraft: ...

    async def suggest_image_prompts(self, context: dict) -> list[str]: ...

    def with_reasoning_effort(self, effort: str | None) -> LLMClient:
        """A client that thinks ``effort`` hard; this one is left unchanged.

        Providers without the concept return themselves.
        """
        ...


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

    def with_reasoning_effort(self, effort: str | None) -> MockLLMClient:
        return self  # nothing to think about offline

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

    async def suggest_image_prompts(self, context: dict) -> list[str]:
        subject = _image_subject(context)
        return [
            f"Bright documentary-style photo of adult learners practising "
            f"{subject} in a modern community college classroom, natural "
            f"window light, regional Australia, no text or logos.",
            f"Close-up of hands working during a {subject} session, shallow "
            f"depth of field, warm tones, authentic training environment, "
            f"no text or logos.",
            f"Wide shot of a friendly trainer guiding a small adult class "
            f"through {subject}, welcoming community college space in the "
            f"NSW Riverina, soft daylight, no text or logos.",
        ]


def _image_subject(context: dict) -> str:
    course = context.get("course") or {}
    return str(course.get("title") or context.get("topic") or "community education")


def render_image_suggestions_prompt(context: dict) -> str:
    """Shared live-model prompt asking for 3 image-generator prompt ideas."""
    course = context.get("course") or {}
    lines = [
        "You are the social media art director for Western Riverina Community "
        "College (WRCC), a community college in the NSW Riverina, Australia.",
        f"Propose exactly {IMAGE_SUGGESTION_COUNT} distinct, detailed prompts "
        "for an AI image generator to illustrate the social post below.",
        "Rules for every prompt:",
        "- Describe a realistic photographic or softly illustrated scene "
        "grounded in the course subject and an adult-education setting in "
        "regional NSW.",
        "- No text, watermarks, logos or brand names inside the image.",
        "- No identifiable real people; generic adult learners only.",
        "- Vary the angle across the three prompts (e.g. close-up detail, "
        "people in action, environment/wide shot).",
        f"Platform: {context.get('platform')}",
        f"Post body: {context.get('post_body')}",
    ]
    if course.get("title"):
        lines.append(f"Course: {course['title']} ({course.get('category') or 'general'})")
    return "\n".join(lines)


def _render_prompt(context: dict) -> str:
    """Render the shared generation context as the live-model prompt."""
    profile = context.get("platform_profile") or {}
    has_course = bool(context.get("course"))
    # A course-less post must not be asked for course facts (a date, a
    # location, an accredited code) that the next line forbids inventing.
    structure = (
        profile.get("structure")
        if has_course
        else profile.get("structure_without_course", profile.get("structure"))
    )
    lines = [
        "You are the social media copywriter for Western Riverina Community "
        "College (WRCC), a community college in the NSW Riverina.",
        f"Write ONE {context.get('platform')} post.",
        f"Angle for this variant: {context.get('variant_style')}.",
        f"Tone: {profile.get('tone')}.",
        f"Structure: {structure}.",
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
        if has_course
        else "No course data is provided: do not state prices, dates, locations, "
        "course codes or accreditation unless they appear in the topic, notes or "
        "reference material above."
    )
    return "\n".join(lines)


T = TypeVar("T")


async def generate_with_retries(
    label: str,
    attempt_once: Callable[[], Awaitable[T]],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
) -> T:
    """Run one provider attempt, retrying up to ``attempts`` tries in total."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await attempt_once()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("%s attempt %d/%d failed: %s", label, attempt, attempts, exc)
            if attempt < attempts:
                await asyncio.sleep(_RETRY_BACKOFF_SECONDS * attempt)
    raise LLMError("AI generation failed after retries.") from last_error


class GeminiLLMClient:
    """Live Gemini client (used when LLM_MOCK=false and LLM_PROVIDER=gemini)."""

    def __init__(self, settings: Settings) -> None:
        from google import genai
        from google.genai import types

        # Bounded like the OpenAI client; google-genai takes milliseconds.
        self._client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=round(settings.llm_timeout_seconds * 1000)
            ),
        )
        self._model = settings.gemini_model
        self._attempts = settings.llm_max_attempts

    def with_reasoning_effort(self, effort: str | None) -> GeminiLLMClient:
        # Gemini's thinking budget is a different knob; not wired up.
        return self

    async def generate_social_post(self, context: dict) -> SocialPostDraft:
        prompt = _render_prompt(context)

        async def attempt_once() -> SocialPostDraft:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": SocialPostDraft,
                },
            )
            return SocialPostDraft.model_validate_json(response.text or "")

        return await generate_with_retries("Gemini", attempt_once, attempts=self._attempts)

    async def suggest_image_prompts(self, context: dict) -> list[str]:
        prompt = render_image_suggestions_prompt(context)

        async def attempt_once() -> list[str]:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": ImagePromptIdeas,
                },
            )
            ideas = ImagePromptIdeas.model_validate_json(response.text or "")
            return ideas.prompts[:IMAGE_SUGGESTION_COUNT]

        return await generate_with_retries(
            "Gemini image prompts", attempt_once, attempts=self._attempts
        )


class OpenAILLMClient:
    """Live OpenAI client (used when LLM_MOCK=false and LLM_PROVIDER=openai)."""

    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        # Left at its defaults the SDK waits up to 600 s per call and retries
        # twice inside each of our attempts — one slow call could hold the
        # request far past the host's ~120 s limit.
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )
        self._model = settings.openai_model
        self._attempts = settings.llm_max_attempts
        # Reasoning effort is the main latency lever (docs/GENERATION-LATENCY-
        # PLAN.md): ~23 s per post at the model's default against ~7 s at "low".
        self._request_options = self._options_for(settings.openai_reasoning_effort)

    def _options_for(self, effort: str | None) -> dict[str, Any]:
        # Absent rather than sent empty: the key is left out entirely for models
        # that would reject it. Typed Any because the SDK's overloads type every
        # keyword individually.
        if effort and supports_reasoning_effort(self._model):
            return {"reasoning_effort": effort}
        return {}

    def with_reasoning_effort(self, effort: str | None) -> OpenAILLMClient:
        """A copy using ``effort`` for its requests; this client is unchanged.

        The copy shares the underlying HTTP client — only its request options
        differ — so one person's choice never leaks into another's request.
        """
        if effort is None:
            return self
        chosen = copy.copy(self)
        chosen._request_options = self._options_for(effort)
        return chosen

    async def generate_social_post(self, context: dict) -> SocialPostDraft:
        # JSON mode has no schema enforcement, so the shape is spelled out in
        # the prompt and validated with pydantic (invalid output retries).
        prompt = _render_prompt(context) + (
            "\nRespond with a single JSON object with exactly these keys: "
            '"body" (string), "hashtags" (array of strings), '
            '"call_to_action" (string or null).'
        )

        async def attempt_once() -> SocialPostDraft:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                **self._request_options,
            )
            content = response.choices[0].message.content or ""
            return SocialPostDraft.model_validate_json(content)

        return await generate_with_retries("OpenAI", attempt_once, attempts=self._attempts)

    async def suggest_image_prompts(self, context: dict) -> list[str]:
        prompt = render_image_suggestions_prompt(context) + (
            "\nRespond with a single JSON object with exactly this key: "
            '"prompts" (array of exactly 3 strings).'
        )

        async def attempt_once() -> list[str]:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                **self._request_options,
            )
            content = response.choices[0].message.content or ""
            ideas = ImagePromptIdeas.model_validate_json(content)
            return ideas.prompts[:IMAGE_SUGGESTION_COUNT]

        return await generate_with_retries(
            "OpenAI image prompts", attempt_once, attempts=self._attempts
        )


def get_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_mock:
        return MockLLMClient()
    if settings.llm_provider == "openai":
        return OpenAILLMClient(settings)
    return GeminiLLMClient(settings)
