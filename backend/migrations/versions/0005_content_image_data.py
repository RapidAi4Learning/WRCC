"""content_images — store PNG bytes in the DB instead of on local disk.

Images previously landed under MEDIA_DIR on the container filesystem, which
does not survive redeploys without a mounted volume. Existing rows (dev-only:
this feature never shipped) reference files that cannot be backfilled from a
migration, so they are deleted before the NOT NULL column is added.

Revision ID: 0005_content_image_data
Revises: 0004_content_images
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_content_image_data"
down_revision: Union[str, None] = "0004_content_images"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM content_images")
    op.add_column(
        "content_images", sa.Column("data", sa.LargeBinary(), nullable=False)
    )
    op.drop_column("content_images", "file_path")


def downgrade() -> None:
    op.execute("DELETE FROM content_images")
    op.add_column(
        "content_images", sa.Column("file_path", sa.Text(), nullable=False)
    )
    op.drop_column("content_images", "data")
