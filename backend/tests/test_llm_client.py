"""Provider selection + OpenAI client behavior (offline, stubbed SDK)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.client import (
    GeminiLLMClient,
    LLMError,
    MockLLMClient,
    OpenAILLMClient,
    get_llm_client,
)
from tests.conftest import make_settings


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


def _openai_client_with(replies: list[str | Exception]) -> OpenAILLMClient:
    client = OpenAILLMClient.__new__(OpenAILLMClient)
    completions = _StubCompletions(replies)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._model = "gpt-5-mini"
    return client


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
    client = _openai_client_with([RuntimeError("boom")])

    with pytest.raises(LLMError):
        await client.generate_social_post({"platform_profile": {}})

    assert len(client._client.chat.completions.calls) == 3
