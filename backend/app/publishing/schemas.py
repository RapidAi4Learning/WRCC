"""Pydantic schemas for the publishing API.

``SocialAccountOut`` has no token field at all — not excluded, not redacted,
structurally absent. A future careless edit to a serializer therefore cannot
leak one.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class AuthorizeUrlOut(BaseModel):
    provider: str
    authorize_url: str


class SocialAccountOut(BaseModel):
    id: str
    platform: str
    external_id: str
    display_name: str
    handle: str | None
    scopes: list[str]
    is_active: bool
    token_expires_at: dt.datetime | None
    # Derived server-side so the UI does not have to reimplement the skew rule.
    token_expired: bool
    connected_at: dt.datetime


class AccountVerificationOut(BaseModel):
    """Result of pinging a connection.

    Always a 200 with `ok`, like the publish endpoint: the check ran, and its
    outcome is the answer. A dead token is information, not a request error.
    """

    account: SocialAccountOut
    ok: bool
    error: str | None = None
    error_code: str | None = None


class PublishRequestBody(BaseModel):
    image_id: uuid.UUID | None = None


class PublicationOut(BaseModel):
    id: str
    content_item_id: str
    social_account_id: str | None
    content_image_id: str | None
    status: str
    external_post_id: str | None
    permalink: str | None
    error: str | None
    error_code: str | None
    request_summary: dict | None
    created_at: dt.datetime
    completed_at: dt.datetime | None


class PreflightOut(BaseModel):
    ready: bool
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    platform: str
    # Exactly what would be sent, so the dialog previews the real thing.
    text: str
    char_count: int
    char_limit: int
    hashtag_count: int
    image_id: str | None
    image_required: bool
    account: SocialAccountOut | None
