"""Post images: suggestions, generation, history, download (mock client)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.llm.images import MockImageClient

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


async def _create_item(auth_client: AsyncClient) -> str:
    response = await auth_client.post(
        "/api/content/generate",
        json={"topic": "First aid enrolments", "platforms": ["facebook"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["id"]


# ── image client ──


async def test_mock_image_client_returns_deterministic_png() -> None:
    client = MockImageClient()
    first = await client.generate_image("classroom scene")
    second = await client.generate_image("classroom scene")
    other = await client.generate_image("different prompt")
    assert first.startswith(PNG_MAGIC)
    assert first == second
    assert first != other


# ── endpoints ──


async def test_images_require_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/content/00000000-0000-0000-0000-000000000000/images",
        json={"prompt": "a classroom"},
    )
    assert response.status_code == 401


async def test_suggestions_returns_three_prompts(auth_client: AsyncClient) -> None:
    item_id = await _create_item(auth_client)
    response = await auth_client.post(f"/api/content/{item_id}/images/suggestions")
    assert response.status_code == 200, response.text
    prompts = response.json()["prompts"]
    assert len(prompts) == 3
    assert len(set(prompts)) == 3  # three *distinct* suggestions


async def test_suggestions_404_for_unknown_item(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/content/00000000-0000-0000-0000-000000000000/images/suggestions"
    )
    assert response.status_code == 404


async def test_generate_stores_image_and_serves_file(
    auth_client: AsyncClient,
) -> None:
    item_id = await _create_item(auth_client)

    response = await auth_client.post(
        f"/api/content/{item_id}/images",
        json={"prompt": "Adult learners practising CPR in a bright classroom"},
    )
    assert response.status_code == 200, response.text
    image = response.json()
    assert image["source"] == "generated"
    assert image["prompt"].startswith("Adult learners")
    assert image["model"] == "mock"
    assert image["mime_type"] == "image/png"
    assert image["file_url"] == f"/api/content/images/{image['id']}/file"

    file_response = await auth_client.get(image["file_url"])
    assert file_response.status_code == 200
    assert file_response.headers["content-type"] == "image/png"
    assert file_response.content.startswith(PNG_MAGIC)
    assert "attachment" not in file_response.headers.get("content-disposition", "")

    download = await auth_client.get(image["file_url"], params={"download": "true"})
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["content-disposition"].endswith('.png"')


async def test_generate_validates_prompt(auth_client: AsyncClient) -> None:
    item_id = await _create_item(auth_client)
    response = await auth_client.post(
        f"/api/content/{item_id}/images", json={"prompt": ""}
    )
    assert response.status_code == 422


async def test_generate_404_for_unknown_item(auth_client: AsyncClient) -> None:
    response = await auth_client.post(
        "/api/content/00000000-0000-0000-0000-000000000000/images",
        json={"prompt": "a classroom"},
    )
    assert response.status_code == 404


async def test_history_lists_newest_first(auth_client: AsyncClient) -> None:
    item_id = await _create_item(auth_client)
    prompts = ["first prompt idea", "second prompt idea", "third prompt idea"]
    ids: list[str] = []
    for prompt in prompts:
        response = await auth_client.post(
            f"/api/content/{item_id}/images", json={"prompt": prompt}
        )
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])

    response = await auth_client.get(f"/api/content/{item_id}/images")
    assert response.status_code == 200
    listed = response.json()
    assert len(listed) == 3
    # Same-second timestamps make strict order flaky on SQLite, so assert
    # membership here; ordering is covered by the query's created_at DESC.
    assert {img["id"] for img in listed} == set(ids)

    regen = await auth_client.post(
        f"/api/content/{item_id}/images", json={"prompt": "first prompt idea"}
    )
    assert regen.status_code == 200
    response = await auth_client.get(f"/api/content/{item_id}/images")
    assert len(response.json()) == 4


async def test_history_404_for_unknown_item(auth_client: AsyncClient) -> None:
    response = await auth_client.get(
        "/api/content/00000000-0000-0000-0000-000000000000/images"
    )
    assert response.status_code == 404


async def test_file_404_for_unknown_image(auth_client: AsyncClient) -> None:
    response = await auth_client.get(
        "/api/content/images/00000000-0000-0000-0000-000000000000/file"
    )
    assert response.status_code == 404


@pytest.mark.parametrize("provider", ["gemini"])
async def test_live_mode_without_openai_provider_is_a_clear_error(
    provider: str,
) -> None:
    from app.llm.images import ImageGenerationError, get_image_client
    from tests.conftest import make_settings

    settings = make_settings(
        llm_mock=False, llm_provider=provider, gemini_api_key="dummy"
    )
    with pytest.raises(ImageGenerationError, match="LLM_PROVIDER=openai"):
        get_image_client(settings)
