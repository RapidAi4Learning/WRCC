"""Shared enum types persisted in the database."""

from __future__ import annotations

import enum


class ScraperRunStatus(enum.StrEnum):
    """Lifecycle of a HITL catalog sync run (crawl → stage → review → apply)."""

    running = "running"
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    failed = "failed"


class ContentPlatform(enum.StrEnum):
    facebook = "facebook"
    instagram = "instagram"
    linkedin = "linkedin"


class ContentStatus(enum.StrEnum):
    """HITL workflow states for a generated content item."""

    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    archived = "archived"
