"""Pydantic schemas for the content API (validation at the boundary)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.content.preferences import WritingPreferences
from app.db.enums import ContentPlatform

# The speeds the Generate screen offers (docs/GENERATION-LATENCY-PLAN.md).
# "high" is deliberately absent: at three platforms it could run up to the
# request deadline, which is exactly the wait this setting exists to avoid.
OfferedReasoningEffort = Literal["minimal", "low", "medium"]

# The image qualities the Media panel offers. "high" is absent for the same
# reason: a single high-quality image can outlast IMAGE_TIMEOUT_SECONDS.
OfferedImageQuality = Literal["low", "medium"]


class GenerateContentRequest(BaseModel):
    writing_preferences: WritingPreferences = Field(default_factory=WritingPreferences)
    topic: str | None = Field(default=None, max_length=300)
    reference_url: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)
    course_id: uuid.UUID | None = None
    platforms: list[ContentPlatform] = Field(min_length=1)
    # Speed against copy quality, chosen per generation. None keeps the
    # server's OPENAI_REASONING_EFFORT.
    reasoning_effort: OfferedReasoningEffort | None = None

    @model_validator(mode="after")
    def _require_grounding(self) -> GenerateContentRequest:
        """D1: the request must be grounded in a topic or a real course."""
        if not (self.topic and self.topic.strip()) and self.course_id is None:
            raise ValueError("Provide a topic or a course_id to ground the generation.")
        return self

    @model_validator(mode="after")
    def _dedupe_platforms(self) -> GenerateContentRequest:
        seen: dict[ContentPlatform, None] = {}
        for platform in self.platforms:
            seen.setdefault(platform, None)
        self.platforms = list(seen)
        return self


class EditContentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


class RejectContentRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class RegenerateContentRequest(BaseModel):
    instruction: str | None = Field(default=None, max_length=1000)


class ContentItemOut(BaseModel):
    id: str
    platform: str
    topic: str | None
    reference_url: str | None
    notes: str | None
    course_id: str | None
    generation_group: str | None
    variant_style: str
    generated_body: str
    edited_body: str | None
    body: str  # edited_body when present, else generated_body
    hashtags: list[str]
    call_to_action: str | None
    status: str
    ai_metadata: dict | None
    created_at: dt.datetime
    updated_at: dt.datetime
    reviewed_at: dt.datetime | None


class GenerateContentResponse(BaseModel):
    generation_group: str
    items: list[ContentItemOut]
    warnings: list[str] = Field(default_factory=list)


class GenerateImageRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    # Draft or standard, chosen per image. None keeps the server's
    # IMAGE_QUALITY.
    quality: OfferedImageQuality | None = None


class MediaAssetOut(BaseModel):
    id: str
    # "generated" or "uploaded" — the UI badges them differently, and only one
    # of the two has a prompt.
    source: str
    prompt: str | None
    model: str | None
    filename: str | None
    mime_type: str
    width: int
    height: int
    byte_size: int
    alt_text: str | None
    created_at: dt.datetime
    file_url: str  # relative API path; the client prefixes its API base


class ItemMediaOut(BaseModel):
    """One entry in a post's ordered selection."""

    media_asset_id: str
    position: int
    alt_text: str | None


class MediaLibraryOut(BaseModel):
    """Everything the media panel needs in one round trip.

    ``library`` is the whole generation group — assets belonging to sibling
    platforms included, which is the point of the group scope — while
    ``selection`` is only what this post sends, in order.
    """

    library: list[MediaAssetOut]
    selection: list[ItemMediaOut]
    # The platform ceiling, so the panel can disable the checkbox rather than
    # letting the operator build a selection the server will refuse.
    max_images: int


class SetSelectionRequest(BaseModel):
    asset_ids: list[uuid.UUID] = Field(default_factory=list)
    # Copy this selection onto the other platforms of the same generation.
    # An action, not a schema property: the selections stay independent
    # afterwards, so LinkedIn can be given a different set.
    apply_to_group: bool = False


class SetSelectionResponse(BaseModel):
    selection: list[ItemMediaOut]
    # Siblings that could not take the selection, named rather than silently
    # trimmed.
    warnings: list[str] = Field(default_factory=list)


class ImageSuggestionsResponse(BaseModel):
    prompts: list[str]
