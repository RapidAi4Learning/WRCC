"""content_images — per-post generated image history (prompt + stored file).

Revision ID: 0004_content_images
Revises: 0003_content_items
Create Date: 2026-07-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_content_images"
down_revision: Union[str, None] = "0003_content_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_images",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_item_id",
            sa.Uuid(),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column(
            "created_by",
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
    )
    op.create_index(
        "ix_content_images_item_created",
        "content_images",
        ["content_item_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_images_item_created", table_name="content_images")
    op.drop_table("content_images")
