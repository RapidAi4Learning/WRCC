"""Writing controls shared by API validation and prompt construction."""

from typing import Literal

from pydantic import BaseModel


class WritingPreferences(BaseModel):
    tone: Literal["auto", "professional", "friendly", "energetic", "inspiring"] = "auto"
    format: Literal["auto", "paragraphs", "bullet_points", "story"] = "auto"
    emojis: Literal["auto", "none", "light", "expressive"] = "auto"


TONE_GUIDANCE = {
    "professional": "Professional, clear and confident; avoid slang and hype.",
    "friendly": "Warm, approachable and conversational, like a helpful local trainer.",
    "energetic": "Upbeat and enthusiastic, with active language; avoid exaggerated claims.",
    "inspiring": "Encouraging and optimistic; focus on achievable learning and growth.",
}
FORMAT_GUIDANCE = {
    "paragraphs": "Use short readable paragraphs separated by blank lines, without bullet lists.",
    "bullet_points": (
        "Use a short hook followed by a concise list of benefits with plain-text bullets."
    ),
    "story": (
        "Use a short narrative arc, without inventing real students, testimonials or outcomes."
    ),
}
EMOJI_GUIDANCE = {
    "none": "Use no emojis anywhere, including the body, hashtags and call to action.",
    "light": "Include 1-2 relevant emojis in the body, used sparingly; none in hashtags or CTA.",
    "expressive": (
        "Include 3-5 relevant emojis in the body; keep it readable and avoid emoji walls."
    ),
}


def writing_guidance(preferences: dict | None) -> list[str]:
    selected = WritingPreferences.model_validate(preferences or {})
    return [
        guidance[value]
        for guidance, value in (
            (TONE_GUIDANCE, selected.tone),
            (FORMAT_GUIDANCE, selected.format),
            (EMOJI_GUIDANCE, selected.emojis),
        )
        if value != "auto"
    ]
