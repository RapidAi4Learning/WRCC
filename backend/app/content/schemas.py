"""Pydantic schemas for the content API (validation at the boundary)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator

from app.db.enums import ContentPlatform


class GenerateContentRequest(BaseModel):
    topic: str | None = Field(default=None, max_length=300)
    reference_url: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)
    course_id: uuid.UUID | None = None
    platforms: list[ContentPlatform] = Field(min_length=1)

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


class ContentImageOut(BaseModel):
    id: str
    content_item_id: str
    prompt: str
    model: str
    created_at: dt.datetime
    file_url: str  # relative API path; the client prefixes its API base


class ImageSuggestionsResponse(BaseModel):
    prompts: list[str]
