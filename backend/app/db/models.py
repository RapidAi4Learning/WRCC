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
    LargeBinary,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base
from app.db.enums import (
    ContentPlatform,
    ContentStatus,
    MediaSource,
    PublishStatus,
    ScraperRunStatus,
)

# JSONB on Postgres, plain JSON elsewhere (SQLite test runs).
PortableJSON = JSON().with_variant(JSONB(), "postgresql")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[dt.datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _updated_at() -> Mapped[dt.datetime]:
    # Client-side onupdate (not func.now()): a server-side onupdate leaves the
    # attribute expired after UPDATE, and reading it later in an async context
    # triggers a sync lazy-load (MissingGreenlet).
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=lambda: dt.datetime.now(dt.UTC),
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


class SocialAccount(Base):
    """A connected publishing destination (Page / IG account / LI organization).

    Access tokens are stored as Fernet ciphertext and are never serialized by
    any response model — see ``app.publishing.schemas``, where the token fields
    are structurally absent rather than merely excluded.
    """

    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_social_accounts_platform_external"),
        # At most one destination per network is the publish target. Enforced by
        # the database so a concurrent activate cannot produce two live targets.
        Index(
            "uq_social_accounts_active_platform",
            "platform",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    platform: Mapped[ContentPlatform] = mapped_column(nullable=False)
    # Page id, Instagram user id, or LinkedIn organization id.
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    # LinkedIn only — Meta's model has no refresh token (Page tokens are long-lived).
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list | None] = mapped_column(PortableJSON)
    # Platform-specific extras: IG's parent page_id, LinkedIn's author URN.
    account_metadata: Mapped[dict | None] = mapped_column(PortableJSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = _created_at()
    updated_at: Mapped[dt.datetime] = _updated_at()


class ContentPublication(Base):
    """One publish *attempt* against one social account.

    Modelled as an attempt rather than a state so retries and failures stay
    inspectable, and so a scheduler can later reuse the same table unchanged.
    """

    __tablename__ = "content_publications"
    __table_args__ = (
        Index("ix_content_publications_item_created", "content_item_id", "created_at"),
        # A post goes out once. The application checks this too, but only the
        # index survives a race between two concurrent requests.
        #
        # It covers `pending` as well as `succeeded` for a reason worth keeping:
        # guarding only `succeeded` would let two requests both pass the
        # application check, both insert a `pending` row, and both reach the
        # network — two real posts — with the index merely stopping the *second*
        # from being recorded. Blocking a second `pending` stops the duplicate
        # before it is sent, which is the only point at which it can be stopped.
        # A `failed` attempt leaves the set, so a retry is free to start.
        Index(
            "uq_content_publications_in_flight",
            "content_item_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'succeeded')"),
            postgresql_where=text("status IN ('pending', 'succeeded')"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    content_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    # SET NULL: the record of what went out must survive a disconnect.
    social_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("social_accounts.id", ondelete="SET NULL")
    )
    # Which assets went out, and in what order, lives in
    # `content_publication_media` — one row per image. A singular column beside
    # that table would be a second record of the same fact, and the pair would
    # drift the first time someone edited one of them.
    status: Mapped[PublishStatus] = mapped_column(
        default=PublishStatus.pending, nullable=False
    )
    external_post_id: Mapped[str | None] = mapped_column(Text)
    permalink: Mapped[str | None] = mapped_column(Text)
    # Counts and ids only — never tokens, never the full payload.
    request_summary: Mapped[dict | None] = mapped_column(PortableJSON)
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    attempted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = _created_at()
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class MediaAsset(Base):
    """One image available to a post: generated by the LLM, or uploaded (D9).

    Scoped to a **generation group**, not to a single item. An item is one
    platform, so owning images per item would mean uploading the same photo
    three times for one campaign. Which assets a given item actually posts —
    and in what order — lives in ``content_item_media`` instead.

    Bytes live in the DB so images survive redeploys with no volume or object
    store. Uploads are normalised at ingest (see ``app.content.media``), which
    is what keeps that arithmetic affordable.
    """

    __tablename__ = "media_assets"
    __table_args__ = (
        Index("ix_media_assets_group_created", "generation_group", "created_at"),
        # Dedupe lookups on re-upload of the same file into the same group.
        Index("ix_media_assets_group_checksum", "generation_group", "checksum"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Nullable because ``ContentItem.generation_group`` is: an item without one
    # falls back to the assets attached to it, and its library is just smaller.
    generation_group: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    source: Mapped[MediaSource] = mapped_column(
        default=MediaSource.generated, nullable=False
    )
    # Both null for an upload, both set for a generation.
    prompt: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    # Sanitised at ingest and used for display only — never to build a path or
    # a Content-Disposition value.
    filename: Mapped[str | None] = mapped_column(Text)
    # Only ever "image/png" or "image/jpeg": whatever arrives is re-encoded to
    # one of the two, so the /file endpoint can serve an honest content type.
    mime_type: Mapped[str] = mapped_column(
        Text, default="image/png", nullable=False
    )
    width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # sha256 of the *stored* bytes, so a re-upload of the same file attaches
    # the existing asset instead of storing a second copy.
    checksum: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Default alt text; a per-item override lives on the join row, because the
    # same picture can want different alt copy on different networks.
    alt_text: Mapped[str | None] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = _created_at()


class ContentItemMedia(Base):
    """The ordered set of assets one item posts (D11).

    ``position`` is the carousel sequence, not decoration: on Instagram the
    first image's aspect ratio crops every other one. Position uniqueness is
    deliberately *not* constrained — a reorder rewrites an item's whole
    selection inside one transaction, so a transient duplicate never exists,
    and a deferrable unique index would buy nothing while costing a
    Postgres-only behaviour the SQLite test path does not share.
    """

    __tablename__ = "content_item_media"
    __table_args__ = (
        UniqueConstraint(
            "content_item_id", "media_asset_id", name="uq_content_item_media_pair"
        ),
        Index("ix_content_item_media_item_position", "content_item_id", "position"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    content_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    alt_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _created_at()


class ContentPublicationMedia(Base):
    """What actually went out with one publish attempt, in order.

    ``SET NULL`` on the asset for the same reason ``social_account_id`` uses it:
    the record of what was published must outlive the thing it referenced.
    """

    __tablename__ = "content_publication_media"
    __table_args__ = (
        Index(
            "ix_content_publication_media_pub_position",
            "publication_id",
            "position",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    publication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("content_publications.id", ondelete="CASCADE"), nullable=False
    )
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[dt.datetime] = _created_at()
