"""Generation is concurrent, bounded, and all-or-nothing.

docs/GENERATION-LATENCY-PLAN.md, phase 3: the production host kills any
request at ~120 s with a 502, and a serial 3-platform generation took ~200 s.
"""

from __future__ import annotations

import logging
import time
import uuid

import pytest
from sqlalchemy import func, select

from app.content.schemas import GenerateContentRequest
from app.content.service import (
    ContentGenerationService,
    ContentWorkflowService,
    GenerationTimeoutError,
)
from app.db.models import ContentItem
from app.llm.client import LLMError, MockLLMClient
from tests.conftest import make_settings
from tests.llm_fakes import SlowLLM

ALL_PLATFORMS = ["facebook", "instagram", "linkedin"]


def _request(platforms: list[str] | None = None) -> GenerateContentRequest:
    return GenerateContentRequest(
        topic="Spring first aid enrolments", platforms=platforms or ALL_PLATFORMS
    )


async def _item_count(session) -> int:
    return (await session.execute(select(func.count()).select_from(ContentItem))).scalar_one()


async def test_platforms_are_generated_concurrently(db_session) -> None:
    llm = SlowLLM(delay=0.3)
    service = ContentGenerationService(db_session, llm, make_settings())

    started = time.perf_counter()
    _, items, _ = await service.generate(_request(), actor_id=uuid.uuid4())
    elapsed = time.perf_counter() - started

    assert len(items) == 9
    assert llm.max_in_flight == 9
    # Serially this is 9 x 0.3 = 2.7 s.
    assert elapsed < 1.2
    # Order is unchanged: platforms as requested, three variants each.
    assert [item.platform.value for item in items] == [
        platform for platform in ALL_PLATFORMS for _ in range(3)
    ]


async def test_the_concurrency_setting_is_respected(db_session) -> None:
    llm = SlowLLM(delay=0.05)
    service = ContentGenerationService(
        db_session, llm, make_settings(llm_max_concurrency=2)
    )

    await service.generate(_request(), actor_id=uuid.uuid4())

    assert llm.max_in_flight == 2


async def test_the_deadline_stops_the_generation_and_saves_nothing(db_session) -> None:
    llm = SlowLLM(delay=5.0)
    service = ContentGenerationService(
        db_session, llm, make_settings(generation_deadline_seconds=0.2)
    )

    started = time.perf_counter()
    with pytest.raises(GenerationTimeoutError):
        await service.generate(_request(), actor_id=uuid.uuid4())
    elapsed = time.perf_counter() - started

    # We answer at the deadline, long before the calls would have finished.
    assert elapsed < 1.0
    assert await _item_count(db_session) == 0


async def test_an_ai_failure_saves_nothing(db_session) -> None:
    llm = SlowLLM(delay=0.3, fail_style="story_led")
    service = ContentGenerationService(db_session, llm, make_settings())

    with pytest.raises(LLMError):
        await service.generate(_request(), actor_id=uuid.uuid4())

    # All or nothing: no platform's variants are kept when one fails.
    assert await _item_count(db_session) == 0


async def test_regeneration_respects_the_deadline(db_session) -> None:
    generated = ContentGenerationService(db_session, MockLLMClient(), make_settings())
    _, items, _ = await generated.generate(_request(["facebook"]), actor_id=uuid.uuid4())

    workflow = ContentWorkflowService(
        db_session, SlowLLM(delay=5.0), make_settings(generation_deadline_seconds=0.2)
    )
    with pytest.raises(GenerationTimeoutError):
        await workflow.regenerate(items[0].id, actor_id=uuid.uuid4())

    assert await _item_count(db_session) == 3


async def test_each_generation_logs_how_long_it_took(db_session, caplog) -> None:
    service = ContentGenerationService(db_session, SlowLLM(delay=0.01), make_settings())

    with caplog.at_level(logging.INFO, logger="app.content.service"):
        await service.generate(_request(["facebook"]), actor_id=uuid.uuid4())

    lines = [record.getMessage() for record in caplog.records]
    assert any("Generated 3 posts" in line and "facebook" in line for line in lines), lines
