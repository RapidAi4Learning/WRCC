"""content_items — persistent generation history + HITL workflow (Fase 2).

Revision ID: 0003_content_items
Revises: 0002_catalog
Create Date: 2026-07-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_content_items"
down_revision: Union[str, None] = "0002_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_platform = sa.Enum("facebook", "instagram", "linkedin", name="contentplatform")
_status = sa.Enum(
    "draft",
    "pending_approval",
    "approved",
    "rejected",
    "archived",
    name="contentstatus",
)


def upgrade() -> None:
    op.create_table(
        "content_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("platform", _platform, nullable=False),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("reference_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "course_id",
            sa.Uuid(),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("generation_group", sa.Uuid(), nullable=True),
        sa.Column("variant_style", sa.Text(), nullable=False),
        sa.Column("generated_body", sa.Text(), nullable=False),
        sa.Column("edited_body", sa.Text(), nullable=True),
        sa.Column("hashtags", postgresql.JSONB(), nullable=True),
        sa.Column("call_to_action", sa.Text(), nullable=True),
        sa.Column("status", _status, nullable=False),
        sa.Column("ai_metadata", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_content_items_platform_status_created",
        "content_items",
        ["platform", "status", "created_at"],
    )
    op.create_index(
        "ix_content_items_generation_group", "content_items", ["generation_group"]
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_generation_group", table_name="content_items")
    op.drop_index(
        "ix_content_items_platform_status_created", table_name="content_items"
    )
    op.drop_table("content_items")
    _status.drop(op.get_bind(), checkfirst=True)
    _platform.drop(op.get_bind(), checkfirst=True)
