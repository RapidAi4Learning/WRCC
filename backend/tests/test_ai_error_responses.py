"""When the AI fails or runs late, the API says so — never the proxy's 502.

docs/GENERATION-LATENCY-PLAN.md, phase 5. A 502 is what the production host
returns when it kills a request; the app answering 502 itself (as the image
endpoints used to) made the two indistinguishable. Every AI failure is now a
503 with a message the person reading the screen can act on — the frontend
shows `detail` as-is.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.api.content import AI_TIMEOUT_DETAIL, AI_UNAVAILABLE_DETAIL, get_llm
from app.api.images import SUGGESTIONS_UNAVAILABLE_DETAIL
from app.config import get_settings
from app.llm.client import LLMError
from app.llm.images import ImageGenerationError
from tests.conftest import make_settings
from tests.llm_fakes import SlowLLM

GENERATE = {"topic": "Spring first aid enrolments", "platforms": ["facebook"]}
SERVICE_UNAVAILABLE = 503


class _FailingSuggestions(SlowLLM):
    async def suggest_image_prompts(self, context: dict) -> list[str]:
        raise LLMError("AI generation failed after retries.")


class _FailingImages:
    async def generate_image(self, prompt: str) -> bytes:
        from app.llm.images import IMAGE_UNAVAILABLE_MESSAGE

        raise ImageGenerationError(IMAGE_UNAVAILABLE_MESSAGE)


async def _create_item(auth_client: AsyncClient) -> str:
    response = await auth_client.post("/api/content/generate", json=GENERATE)
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["id"]


async def test_generate_answers_503_when_the_ai_fails(app, auth_client: AsyncClient) -> None:
    app.dependency_overrides[get_llm] = lambda: SlowLLM(delay=0.01, fail_style="direct")

    response = await auth_client.post("/api/content/generate", json=GENERATE)

    assert response.status_code == SERVICE_UNAVAILABLE
    assert response.json()["detail"] == AI_UNAVAILABLE_DETAIL


async def test_generate_answers_503_at_the_deadline_and_saves_nothing(
    app, auth_client: AsyncClient
) -> None:
    app.dependency_overrides[get_settings] = lambda: make_settings(
        generation_deadline_seconds=0.2
    )
    app.dependency_overrides[get_llm] = lambda: SlowLLM(delay=5.0)

    response = await auth_client.post("/api/content/generate", json=GENERATE)

    assert response.status_code == SERVICE_UNAVAILABLE
    assert response.json()["detail"] == AI_TIMEOUT_DETAIL
    history = await auth_client.get("/api/content")
    assert history.json() == []


async def test_regenerate_answers_503_when_the_ai_fails(app, auth_client: AsyncClient) -> None:
    item_id = await _create_item(auth_client)
    app.dependency_overrides[get_llm] = lambda: SlowLLM(delay=0.01, fail_style="direct")

    response = await auth_client.post(f"/api/content/{item_id}/regenerate")

    assert response.status_code == SERVICE_UNAVAILABLE
    assert response.json()["detail"] == AI_UNAVAILABLE_DETAIL


async def test_image_suggestions_answer_503_not_502(app, auth_client: AsyncClient) -> None:
    item_id = await _create_item(auth_client)
    app.dependency_overrides[get_llm] = lambda: _FailingSuggestions()

    response = await auth_client.post(f"/api/content/{item_id}/images/suggestions")

    assert response.status_code == SERVICE_UNAVAILABLE
    assert response.json()["detail"] == SUGGESTIONS_UNAVAILABLE_DETAIL


async def test_image_generation_answers_503_with_a_readable_message(
    auth_client: AsyncClient, monkeypatch
) -> None:
    item_id = await _create_item(auth_client)
    monkeypatch.setattr("app.content.media.get_image_client", lambda settings: _FailingImages())

    response = await auth_client.post(
        f"/api/content/{item_id}/images", json={"prompt": "a bright classroom"}
    )

    assert response.status_code == SERVICE_UNAVAILABLE
    assert "try again" in response.json()["detail"].lower()
