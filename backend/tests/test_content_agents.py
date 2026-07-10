"""Generator agent + mock LLM determinism + validation baseline (unit)."""

from __future__ import annotations

import pytest

from app.agents.content_generator import (
    CONTENT_VARIANT_STYLES,
    PLATFORM_PROFILES,
    build_generation_context,
    run_content_generator_variants,
)
from app.agents.validation import validate_generated_content
from app.db.enums import ContentPlatform
from app.llm.client import MockLLMClient


def test_platform_profiles_cover_all_platforms() -> None:
    assert set(PLATFORM_PROFILES) == {p.value for p in ContentPlatform}
    for profile in PLATFORM_PROFILES.values():
        assert profile["min_length"] < profile["max_length"]
        assert profile["hashtags_min"] <= profile["hashtags_max"]


def test_context_carries_profile_and_grounding() -> None:
    context = build_generation_context(
        platform=ContentPlatform.linkedin,
        variant_style="direct",
        topic="First aid courses",
        notes="Mention Griffith",
        course_facts={"title": "HLTAID011"},
        reference_excerpt="excerpt",
    )
    assert context["platform"] == "linkedin"
    assert context["platform_profile"] is PLATFORM_PROFILES["linkedin"]
    assert context["topic"] == "First aid courses"
    assert context["course"] == {"title": "HLTAID011"}


@pytest.mark.parametrize("platform", list(ContentPlatform))
async def test_mock_variants_are_distinct_and_profile_compliant(
    platform: ContentPlatform,
) -> None:
    drafts = await run_content_generator_variants(
        llm=MockLLMClient(),
        platform=platform,
        topic="Provide First Aid",
        course_facts={
            "title": "HLTAID011 Provide First Aid",
            "category": "First Aid",
            "enrollment_url": "https://wrcc.nsw.edu.au/course-enrol?instance_id=1",
            "upcoming_offerings": [
                {"start_date": "2026-08-07", "location": "WRCC Griffith", "price": 185.0}
            ],
        },
    )

    assert len(drafts) == 3
    assert {d.style for d in drafts} == set(CONTENT_VARIANT_STYLES)
    # Deterministic mock still produces genuinely different bodies per style.
    assert len({d.body for d in drafts}) == 3
    # Mock output respects the platform profile → zero violations.
    for draft in drafts:
        assert draft.violation_count == 0, (platform, draft.style)
        assert draft.call_to_action


async def test_mock_is_deterministic() -> None:
    async def one() -> list[str]:
        drafts = await run_content_generator_variants(
            llm=MockLLMClient(), platform=ContentPlatform.facebook, topic="Yoga"
        )
        return [d.body for d in drafts]

    assert await one() == await one()


def test_validation_flags_all_violation_kinds() -> None:
    violations = validate_generated_content(
        platform=ContentPlatform.linkedin,
        body="too short",
        hashtags=[],
        call_to_action=None,
    )
    assert any("too short" in v for v in violations)
    assert any("too few hashtags" in v for v in violations)
    assert any("missing call to action" in v for v in violations)

    too_long = validate_generated_content(
        platform=ContentPlatform.instagram,
        body="x" * 500,
        hashtags=["#a"] * 20,
        call_to_action="Go",
    )
    assert any("too long" in v for v in too_long)
    assert any("too many hashtags" in v for v in too_long)


def test_validation_passes_compliant_post() -> None:
    assert (
        validate_generated_content(
            platform=ContentPlatform.facebook,
            body="x" * 300,
            hashtags=["#a", "#b", "#c"],
            call_to_action="Book your spot.",
        )
        == []
    )
