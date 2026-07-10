"""ORM models (schema per docs/PLAN.md §4).

Types are chosen to work on PostgreSQL (production) and SQLite/aiosqlite
(unit tests): JSON columns use a JSONB variant on Postgres, and UUID columns
use SQLAlchemy's portable ``Uuid`` type.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.db.enums import ContentPlatform, ContentStatus, ScraperRunStatus

# JSONB on Postgres, plain JSON elsewhere (SQLite test runs).
PortableJSON = JSON().with_variant(JSONB(), "postgresql")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[dt.datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _updated_at() -> Mapped[dt.datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class User(Base):
    """Basic login (§4a): seeded users only, no roles/self-service."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = _created_at()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload_diff: Mapped[dict | None] = mapped_column(PortableJSON)
    created_at: Mapped[dt.datetime] = _created_at()


class Course(Base):
    """Stable course grouping; offerings hold the scheduled instances."""

    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    course_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_accredited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    # False = disappeared from the site (soft delete via sync, never hard-deleted).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()


class CourseOffering(Base):
    """One row per scheduled instance (aXcelerate instance) of a course."""

    __tablename__ = "course_offerings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    offering_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(10, 2))
    gst: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active", nullable=False)
    places_available: Mapped[int | None] = mapped_column(Integer)
    places_text: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    finish_date: Mapped[dt.date | None] = mapped_column(Date)
    time_text: Mapped[str | None] = mapped_column(Text)
    session_count: Mapped[int | None] = mapped_column(Integer)
    session_hours: Mapped[float | None] = mapped_column(Numeric(6, 2))
    enrollment_url: Mapped[str | None] = mapped_column(Text)
    detail_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()


class ScraperRun(Base):
    """HITL sync lifecycle: crawl → stage changeset → approve/reject → apply."""

    __tablename__ = "scraper_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[ScraperRunStatus] = mapped_column(
        default=ScraperRunStatus.running, nullable=False
    )
    courses_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    offerings_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    changeset: Mapped[dict | None] = mapped_column(PortableJSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = _created_at()


class ContentItem(Base):
    """Persistent history of every generated variant (requirement 3)."""

    __tablename__ = "content_items"
    __table_args__ = (
        Index("ix_content_items_platform_status_created", "platform", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    platform: Mapped[ContentPlatform] = mapped_column(nullable=False)
    topic: Mapped[str | None] = mapped_column(Text)
    reference_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL")
    )
    # Links the 3 variants produced by one generation request.
    generation_group: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    variant_style: Mapped[str] = mapped_column(Text, nullable=False)
    generated_body: Mapped[str] = mapped_column(Text, nullable=False)
    edited_body: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list | None] = mapped_column(PortableJSON)
    call_to_action: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ContentStatus] = mapped_column(
        default=ContentStatus.draft, nullable=False
    )
    ai_metadata: Mapped[dict | None] = mapped_column(PortableJSON)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()
