"""Deterministic rule baseline used to rank generated variants.

Pure functions over the platform profile — no LLM call, no DB.
"""

from __future__ import annotations

from app.db.enums import ContentPlatform


def validate_generated_content(
    *,
    platform: ContentPlatform,
    body: str,
    hashtags: list[str],
    call_to_action: str | None,
) -> list[str]:
    """Return the list of profile violations (empty = fully compliant)."""
    from app.agents.content_generator import PLATFORM_PROFILES

    profile = PLATFORM_PROFILES[platform.value]
    violations: list[str] = []

    length = len(body or "")
    if length < profile["min_length"]:
        violations.append(
            f"body too short for {platform.value} "
            f"({length} < {profile['min_length']} chars)"
        )
    elif length > profile["max_length"]:
        violations.append(
            f"body too long for {platform.value} "
            f"({length} > {profile['max_length']} chars)"
        )

    count = len(hashtags or [])
    if count < profile["hashtags_min"]:
        violations.append(
            f"too few hashtags ({count} < {profile['hashtags_min']})"
        )
    elif count > profile["hashtags_max"]:
        violations.append(
            f"too many hashtags ({count} > {profile['hashtags_max']})"
        )

    if not (call_to_action or "").strip():
        violations.append("missing call to action")

    return violations
