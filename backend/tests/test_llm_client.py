"""Provider selection + OpenAI client behavior (offline, stubbed SDK)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agents.content_generator import build_generation_context
from app.db.enums import ContentPlatform
from app.llm.client import (
    GeminiLLMClient,
    LLMError,
    MockLLMClient,
    OpenAILLMClient,
    _render_prompt,
    get_llm_client,
)
from tests.conftest import make_settings

COURSE = {"title": "Provide First Aid", "course_code": "HLTAID011", "price": 185.0}


class _StubCompletions:
    """Stands in for AsyncOpenAI().chat.completions with scripted replies."""

    def __init__(self, replies: list[str | Exception]) -> None:
        self._replies = replies
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        reply = self._replies[min(len(self.calls), len(self._replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        message = SimpleNamespace(content=reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _openai_client_with(
    replies: list[str | Exception], *, attempts: int = 2
) -> OpenAILLMClient:
    client = OpenAILLMClient.__new__(OpenAILLMClient)
    completions = _StubCompletions(replies)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._model = "gpt-5-mini"
    client._attempts = attempts
    client._request_options = {}
    return client


class _StubImages:
    """Stands in for AsyncOpenAI().images; always fails, counting the calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, **kwargs: Any) -> Any:
        self.calls += 1
        raise RuntimeError("image provider down")


class _RecordingAsyncOpenAI:
    """Replaces openai.AsyncOpenAI so the real client constructors run, and
    records how they configured it and what each request asked for."""

    last: _RecordingAsyncOpenAI | None = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.completions = _StubCompletions(
            [json.dumps({"body": "ok", "hashtags": [], "call_to_action": None})]
        )
        self.chat = SimpleNamespace(completions=self.completions)
        self.images = _StubImages()
        _RecordingAsyncOpenAI.last = self


def _live_openai(monkeypatch, **overrides: Any) -> tuple[OpenAILLMClient, _RecordingAsyncOpenAI]:
    monkeypatch.setattr("openai.AsyncOpenAI", _RecordingAsyncOpenAI)
    settings = make_settings(
        llm_mock=False, llm_provider="openai", openai_api_key="k", **overrides
    )
    client = OpenAILLMClient(settings)
    assert _RecordingAsyncOpenAI.last is not None
    return client, _RecordingAsyncOpenAI.last


@pytest.fixture
def no_backoff(monkeypatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.llm.client.asyncio.sleep", no_sleep)


def test_get_llm_client_prefers_mock() -> None:
    assert isinstance(get_llm_client(make_settings()), MockLLMClient)


def test_get_llm_client_selects_provider() -> None:
    openai_settings = make_settings(
        llm_mock=False, llm_provider="openai", openai_api_key="k"
    )
    assert isinstance(get_llm_client(openai_settings), OpenAILLMClient)

    gemini_settings = make_settings(
        llm_mock=False, llm_provider="gemini", gemini_api_key="k"
    )
    assert isinstance(get_llm_client(gemini_settings), GeminiLLMClient)


async def test_openai_client_parses_structured_reply() -> None:
    reply = json.dumps(
        {
            "body": "Enrol in First Aid at WRCC.",
            "hashtags": ["#WRCC", "#FirstAid"],
            "call_to_action": "Enrol today.",
        }
    )
    client = _openai_client_with([reply])

    draft = await client.generate_social_post(
        {"platform": "facebook", "variant_style": "direct", "platform_profile": {}}
    )

    assert draft.body == "Enrol in First Aid at WRCC."
    assert draft.hashtags == ["#WRCC", "#FirstAid"]
    assert draft.call_to_action == "Enrol today."
    call = client._client.chat.completions.calls[0]
    assert call["model"] == "gpt-5-mini"
    assert call["response_format"] == {"type": "json_object"}
    # The JSON contract must be spelled out because json_object mode has no schema.
    assert '"hashtags"' in call["messages"][0]["content"]


async def test_openai_client_retries_invalid_json_then_succeeds(monkeypatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.llm.client.asyncio.sleep", no_sleep)
    good = json.dumps({"body": "ok", "hashtags": [], "call_to_action": None})
    client = _openai_client_with(["not-json", good])

    draft = await client.generate_social_post({"platform_profile": {}})

    assert draft.body == "ok"
    assert len(client._client.chat.completions.calls) == 2


async def test_openai_client_raises_llm_error_after_retries(monkeypatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.llm.client.asyncio.sleep", no_sleep)
    client = _openai_client_with([RuntimeError("boom")], attempts=2)

    with pytest.raises(LLMError):
        await client.generate_social_post({"platform_profile": {}})

    assert len(client._client.chat.completions.calls) == 2


# ── Prompt without a course (docs/GENERATION-LATENCY-PLAN.md, phase 4) ──


def _prompt(platform: ContentPlatform, *, course: dict | None = None) -> str:
    return _render_prompt(
        build_generation_context(
            platform=platform,
            variant_style="direct",
            topic=None if course else "Spring first aid in Griffith",
            course_facts=course,
        )
    )


@pytest.mark.parametrize(
    ("platform", "course_only_ask"),
    [
        (ContentPlatform.facebook, "date/location"),
        (ContentPlatform.linkedin, "accredited code"),
    ],
)
def test_prompt_without_course_does_not_ask_for_course_facts(
    platform: ContentPlatform, course_only_ask: str
) -> None:
    # Asking for a date or an accredited code while forbidding the model to
    # invent one is what made it fill the gap ("WRCC Griffith campus").
    prompt = _prompt(platform)

    assert course_only_ask not in prompt
    assert "only use the course data provided" not in prompt
    assert "No course data is provided" in prompt


@pytest.mark.parametrize(
    ("platform", "course_only_ask"),
    [
        (ContentPlatform.facebook, "date/location"),
        (ContentPlatform.linkedin, "accredited code"),
    ],
)
def test_prompt_with_course_is_unchanged(
    platform: ContentPlatform, course_only_ask: str
) -> None:
    prompt = _prompt(platform, course=COURSE)

    assert course_only_ask in prompt
    assert "only use the course data provided" in prompt
    assert "No course data is provided" not in prompt


# ── Latency bounds (docs/GENERATION-LATENCY-PLAN.md, phase 2) ──


def test_openai_client_is_bounded_with_a_single_retry_layer(monkeypatch) -> None:
    _, sdk = _live_openai(monkeypatch)
    # The SDK default is 600 s per call and 2 retries of its own inside each of
    # ours — together they could hold a request for many minutes.
    assert sdk.kwargs["timeout"] == 40.0
    assert sdk.kwargs["max_retries"] == 0


async def test_reasoning_models_get_the_configured_effort(monkeypatch) -> None:
    client, sdk = _live_openai(monkeypatch, openai_model="gpt-5-mini")

    await client.generate_social_post({"platform_profile": {}})

    assert sdk.completions.calls[0]["reasoning_effort"] == "low"


async def test_image_suggestions_get_the_configured_effort_too(monkeypatch) -> None:
    client, sdk = _live_openai(monkeypatch, openai_reasoning_effort="minimal")
    sdk.completions._replies = [json.dumps({"prompts": ["a", "b", "c"]})]

    await client.suggest_image_prompts({"platform": "facebook"})

    assert sdk.completions.calls[0]["reasoning_effort"] == "minimal"


async def test_non_reasoning_models_never_get_an_effort(monkeypatch) -> None:
    # They reject the parameter with a 400, so switching OPENAI_MODEL must not
    # turn every generation into an error.
    client, sdk = _live_openai(monkeypatch, openai_model="gpt-4.1-mini")

    await client.generate_social_post({"platform_profile": {}})

    assert "reasoning_effort" not in sdk.completions.calls[0]


async def test_blank_effort_sends_nothing(monkeypatch) -> None:
    client, sdk = _live_openai(monkeypatch, openai_reasoning_effort="")

    await client.generate_social_post({"platform_profile": {}})

    assert "reasoning_effort" not in sdk.completions.calls[0]


async def test_attempts_follow_the_setting(monkeypatch, no_backoff) -> None:
    client, sdk = _live_openai(monkeypatch, llm_max_attempts=1)
    sdk.completions._replies = [RuntimeError("timed out")]

    with pytest.raises(LLMError):
        await client.generate_social_post({"platform_profile": {}})

    assert len(sdk.completions.calls) == 1


def test_gemini_client_is_bounded(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class _RecordingGenaiClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("google.genai.Client", _RecordingGenaiClient)
    GeminiLLMClient(
        make_settings(llm_mock=False, llm_provider="gemini", gemini_api_key="k")
    )

    # google-genai takes its timeout in milliseconds.
    assert captured["http_options"].timeout == 40_000


async def test_image_client_makes_one_bounded_attempt(monkeypatch) -> None:
    from app.llm.images import ImageGenerationError, OpenAIImageClient

    monkeypatch.setattr("openai.AsyncOpenAI", _RecordingAsyncOpenAI)
    client = OpenAIImageClient(
        make_settings(llm_mock=False, llm_provider="openai", openai_api_key="k")
    )
    sdk = _RecordingAsyncOpenAI.last
    assert sdk is not None

    with pytest.raises(ImageGenerationError):
        await client.generate_image("a classroom")

    # An image takes tens of seconds: a retry after a timeout would itself run
    # past the proxy limit, so there is exactly one attempt.
    assert sdk.images.calls == 1
    assert sdk.kwargs["timeout"] == 100.0
    assert sdk.kwargs["max_retries"] == 0
