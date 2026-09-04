"""Preflight rules — the table in docs/PUBLISH-PLAN.md §5.5, exhaustively.

These are pure functions, so the whole matrix is cheap to assert. They are also
the single source of truth for "can this go out?", which makes them the place a
platform-limit change must be visible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db.enums import ContentPlatform, ContentStatus
from app.publishing.rules import (
    LIMITS,
    PreflightContext,
    compose_post_text,
    preflight,
)

ALL_PLATFORMS = list(ContentPlatform)


def _ready_context(platform: ContentPlatform, **overrides) -> PreflightContext:
    """A context that passes every rule, so each test breaks exactly one."""
    defaults = {
        "platform": platform,
        "status": ContentStatus.approved,
        "text": "A perfectly reasonable post.",
        "hashtag_count": 2,
        "image_count": 1,
        "account_connected": True,
    }
    defaults.update(overrides)
    return PreflightContext(**defaults)  # type: ignore[arg-type]


# ── compose_post_text (must mirror frontend/lib/postText.ts) ──


def _shared_cases() -> list[dict]:
    """The cross-language contract in shared/post-text-cases.json.

    The frontend suite iterates the same file. Asserting hardcoded strings on
    each side independently would let one implementation change while both
    suites stayed green — and the first sign would be a Copy button producing
    text that differs from what was published.
    """
    path = Path(__file__).resolve().parents[2] / "shared" / "post-text-cases.json"
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", _shared_cases(), ids=lambda case: case["name"])
def test_compose_matches_the_shared_contract(case: dict) -> None:
    assert (
        compose_post_text(case["body"], case["call_to_action"], case["hashtags"])
        == case["expected"]
    )


def test_compose_orders_body_then_cta_then_hashtags() -> None:
    assert compose_post_text("Body.", "Enrol now.", ["#first", "#aid"]) == (
        "Body.\n\nEnrol now.\n\n#first #aid"
    )


def test_compose_omits_empty_sections() -> None:
    assert compose_post_text("Body.", None, []) == "Body."
    assert compose_post_text("Body.", "   ", ["  "]) == "Body."


def test_compose_trims_each_section() -> None:
    assert compose_post_text("  Body.  ", " CTA ", [" #tag "]) == "Body.\n\nCTA\n\n#tag"


# ── the happy path ──


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_ready_when_every_rule_passes(platform: ContentPlatform) -> None:
    outcome = preflight(_ready_context(platform))
    assert outcome.ready
    assert outcome.blockers == []


# ── status gate ──


@pytest.mark.parametrize(
    "status",
    [
        ContentStatus.draft,
        ContentStatus.pending_approval,
        ContentStatus.rejected,
        ContentStatus.archived,
    ],
)
def test_only_approved_items_may_publish(status: ContentStatus) -> None:
    outcome = preflight(_ready_context(ContentPlatform.facebook, status=status))
    assert not outcome.ready
    assert any("Only approved posts" in blocker for blocker in outcome.blockers)


def test_already_published_status_blocks() -> None:
    outcome = preflight(
        _ready_context(ContentPlatform.facebook, status=ContentStatus.published)
    )
    assert any("already been published" in blocker for blocker in outcome.blockers)


def test_existing_successful_publication_blocks() -> None:
    outcome = preflight(_ready_context(ContentPlatform.facebook, already_published=True))
    assert any("already been published" in blocker for blocker in outcome.blockers)


# ── account gate ──


def test_missing_account_blocks_and_points_at_settings() -> None:
    outcome = preflight(
        _ready_context(ContentPlatform.linkedin, account_connected=False)
    )
    assert any("Connect one in Settings" in blocker for blocker in outcome.blockers)


def test_expired_token_blocks_with_a_reconnect_message() -> None:
    outcome = preflight(
        _ready_context(ContentPlatform.linkedin, account_token_expired=True)
    )
    assert any("Reconnect it in Settings" in blocker for blocker in outcome.blockers)


# ── pending attempts ──


def test_in_flight_attempt_blocks_without_alarming_wording() -> None:
    outcome = preflight(
        _ready_context(ContentPlatform.facebook, has_pending_attempt=True)
    )
    assert not outcome.ready
    assert any("still running" in blocker for blocker in outcome.blockers)


def test_stale_attempt_tells_the_operator_to_check_the_network() -> None:
    outcome = preflight(
        _ready_context(
            ContentPlatform.facebook,
            has_pending_attempt=True,
            pending_attempt_is_stale=True,
        )
    )
    assert any("never reported back" in blocker for blocker in outcome.blockers)


# ── images ──


def test_instagram_requires_an_image() -> None:
    outcome = preflight(_ready_context(ContentPlatform.instagram, image_count=0))
    assert not outcome.ready
    assert any("require an image" in blocker for blocker in outcome.blockers)


@pytest.mark.parametrize(
    "platform", [ContentPlatform.facebook, ContentPlatform.linkedin]
)
def test_image_is_optional_off_instagram(platform: ContentPlatform) -> None:
    assert preflight(_ready_context(platform, image_count=0)).ready


# ── text length ──


def test_empty_text_blocks() -> None:
    outcome = preflight(_ready_context(ContentPlatform.facebook, text=""))
    assert any("empty" in blocker for blocker in outcome.blockers)


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_text_at_the_limit_is_allowed(platform: ContentPlatform) -> None:
    text = "x" * LIMITS[platform].text_limit
    assert preflight(_ready_context(platform, text=text)).ready


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_text_one_over_the_limit_blocks(platform: ContentPlatform) -> None:
    text = "x" * (LIMITS[platform].text_limit + 1)
    outcome = preflight(_ready_context(platform, text=text))
    assert not outcome.ready
    assert any("characters" in blocker for blocker in outcome.blockers)


# ── hashtags ──


def test_instagram_blocks_above_thirty_hashtags() -> None:
    outcome = preflight(_ready_context(ContentPlatform.instagram, hashtag_count=31))
    assert not outcome.ready
    assert any("hashtags" in blocker for blocker in outcome.blockers)


def test_instagram_allows_exactly_thirty_hashtags() -> None:
    assert preflight(_ready_context(ContentPlatform.instagram, hashtag_count=30)).ready


def test_linkedin_warns_but_does_not_block_on_many_hashtags() -> None:
    outcome = preflight(_ready_context(ContentPlatform.linkedin, hashtag_count=8))
    assert outcome.ready
    assert any("hashtags" in warning for warning in outcome.warnings)


def test_facebook_warns_above_ten_hashtags() -> None:
    outcome = preflight(_ready_context(ContentPlatform.facebook, hashtag_count=11))
    assert outcome.ready
    assert outcome.warnings


# ── multiple failures ──


def test_every_blocker_is_reported_not_just_the_first() -> None:
    outcome = preflight(
        PreflightContext(
            platform=ContentPlatform.instagram,
            status=ContentStatus.draft,
            text="",
            hashtag_count=99,
            image_count=0,
            account_connected=False,
        )
    )
    # status, account, image, empty text, hashtags — the operator should see
    # everything wrong at once, not fix one thing per round trip.
    assert len(outcome.blockers) == 5
