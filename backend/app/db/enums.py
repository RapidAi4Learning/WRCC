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
    # Live on the network. Reachable only from `approved` and only via a
    # successful publish — never set by an ordinary workflow transition.
    published = "published"


class PublishStatus(enum.StrEnum):
    """Outcome of a single publish attempt (one ``content_publications`` row).

    ``pending`` is written *before* the network call, so an attempt that dies
    mid-flight leaves evidence instead of silence: we may have posted and lost
    the response, and that is a different situation from never having tried.
    """

    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
