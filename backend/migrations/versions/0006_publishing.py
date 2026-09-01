"""social_accounts + content_publications — publishing to FB/IG/LinkedIn.

Revision ID: 0006_publishing
Revises: 0005_content_image_data
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_publishing"
down_revision: Union[str, None] = "0005_content_image_data"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reuse the existing native enum rather than re-creating it.
_platform = postgresql.ENUM(
    "facebook", "instagram", "linkedin", name="contentplatform", create_type=False
)
_publish_status = sa.Enum("pending", "succeeded", "failed", name="publishstatus")


def upgrade() -> None:
    # `contentstatus` is a native Postgres enum (see 0003). Adding a member is
    # a DDL change, not a no-op. autocommit_block sidesteps both the pre-PG12
    # "cannot run inside a transaction block" error and the "unsafe use of new
    # value" error that fires when the value is referenced in the same
    # transaction that added it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE contentstatus ADD VALUE IF NOT EXISTS 'published'")

    op.create_table(
        "social_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("platform", _platform, nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.JSONB(), nullable=True),
        sa.Column("account_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "connected_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "platform", "external_id", name="uq_social_accounts_platform_external"
        ),
    )
    # One publish destination per network, enforced by the database so a
    # concurrent activate cannot leave two live targets.
    op.create_index(
        "uq_social_accounts_active_platform",
        "social_accounts",
        ["platform"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "content_publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_item_id",
            sa.Uuid(),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "social_account_id",
            sa.Uuid(),
            sa.ForeignKey("social_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "content_image_id",
            sa.Uuid(),
            sa.ForeignKey("content_images.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", _publish_status, nullable=False),
        sa.Column("external_post_id", sa.Text(), nullable=True),
        sa.Column("permalink", sa.Text(), nullable=True),
        sa.Column("request_summary", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "attempted_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_content_publications_item_created",
        "content_publications",
        ["content_item_id", "created_at"],
    )
    # A post goes out once. The service checks this too; the index is what makes
    # a double-publish impossible under a race.
    op.create_index(
        "uq_content_publications_succeeded",
        "content_publications",
        ["content_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_content_publications_succeeded", table_name="content_publications"
    )
    op.drop_index(
        "ix_content_publications_item_created", table_name="content_publications"
    )
    op.drop_table("content_publications")
    op.drop_index("uq_social_accounts_active_platform", table_name="social_accounts")
    op.drop_table("social_accounts")
    _publish_status.drop(op.get_bind(), checkfirst=True)
    # 'published' is intentionally left on the contentstatus enum: Postgres has
    # no DROP VALUE, and removing it would mean rebuilding the type and every
    # column that uses it. A spare enum member is harmless.
