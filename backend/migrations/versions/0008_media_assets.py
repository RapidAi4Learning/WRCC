"""content_images → media_assets, plus per-item and per-publication selection.

Revision ID: 0008_media_assets
Revises: 0007_in_flight_publish_index
Create Date: 2026-09-04

Implements D9/D11 of docs/MEDIA-PLAN.md. Three moves:

*Rename, do not recreate.* ``content_images`` becomes ``media_assets`` so the
primary keys survive; recreating the table would orphan every
``content_publications`` row from the bytes it published.

*The implicit becomes explicit.* Publishing used to fall back to "the most
recent image of this item" with nothing in the UI saying so. The backfill turns
exactly that image into a real ``content_item_media`` row, so behaviour is
preserved rather than reset. Older images stay in the library, unattached.

*Batch mode for the alters.* Postgres is the production target, but every alter
here is wrapped so the same migration runs on SQLite, which is what lets a test
exercise upgrade *and* downgrade against a seeded database.
"""

from __future__ import annotations

import hashlib
import io
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_media_assets"
down_revision: Union[str, None] = "0007_in_flight_publish_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_media_source = sa.Enum("generated", "uploaded", name="mediasource")

# Rows read at a time during the byte-reading backfill. Each row carries a
# full image, so the whole table must not be materialised at once.
_BATCH = 50


def _dimensions(data: bytes) -> tuple[int, int]:
    """(width, height) from the header, or (0, 0) for bytes PIL cannot read.

    A migration must not fail on one unreadable legacy row: zero dimensions are
    honest ("we do not know"), and the preflight treats them as a problem to
    report rather than a crash.
    """
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:  # noqa: BLE001 - any unreadable row backfills as unknown
        return 0, 0


def _backfill_assets(connection: sa.Connection) -> None:
    """Fill the new descriptive columns from the bytes already stored."""
    ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM media_assets"))]
    for start in range(0, len(ids), _BATCH):
        chunk = ids[start : start + _BATCH]
        rows = connection.execute(
            sa.text("SELECT id, data FROM media_assets WHERE id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": chunk},
        ).fetchall()
        for asset_id, data in rows:
            payload = bytes(data or b"")
            width, height = _dimensions(payload)
            connection.execute(
                sa.text(
                    "UPDATE media_assets SET width = :w, height = :h, "
                    "byte_size = :size, checksum = :checksum WHERE id = :id"
                ),
                {
                    "w": width,
                    "h": height,
                    "size": len(payload),
                    "checksum": hashlib.sha256(payload).hexdigest(),
                    "id": asset_id,
                },
            )


def upgrade() -> None:
    connection = op.get_bind()
    is_postgres = connection.dialect.name == "postgresql"
    if is_postgres:
        _media_source.create(connection, checkfirst=True)

    op.rename_table("content_images", "media_assets")

    # ── 1. widen media_assets ──
    with op.batch_alter_table("media_assets") as batch:
        batch.add_column(sa.Column("generation_group", sa.Uuid(), nullable=True))
        batch.add_column(
            sa.Column(
                "source",
                _media_source if is_postgres else sa.Text(),
                nullable=False,
                server_default="generated",
            )
        )
        batch.add_column(sa.Column("filename", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column(
                "mime_type", sa.Text(), nullable=False, server_default="image/png"
            )
        )
        batch.add_column(
            sa.Column("width", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("height", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("checksum", sa.Text(), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("alt_text", sa.Text(), nullable=True))
        # An upload has neither; both were NOT NULL when only generation existed.
        batch.alter_column("prompt", existing_type=sa.Text(), nullable=True)
        batch.alter_column("model", existing_type=sa.Text(), nullable=True)

    op.execute(
        "UPDATE media_assets SET generation_group = ("
        "SELECT content_items.generation_group FROM content_items "
        "WHERE content_items.id = media_assets.content_item_id)"
    )
    _backfill_assets(connection)

    op.drop_index("ix_content_images_item_created", table_name="media_assets")
    op.create_index(
        "ix_media_assets_group_created",
        "media_assets",
        ["generation_group", "created_at"],
    )
    op.create_index(
        "ix_media_assets_group_checksum",
        "media_assets",
        ["generation_group", "checksum"],
    )

    # ── 2. the per-item selection ──
    op.create_table(
        "content_item_media",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_item_id",
            sa.Uuid(),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_asset_id",
            sa.Uuid(),
            sa.ForeignKey("media_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "content_item_id", "media_asset_id", name="uq_content_item_media_pair"
        ),
    )
    op.create_index(
        "ix_content_item_media_item_position",
        "content_item_media",
        ["content_item_id", "position"],
    )

    # Preserve today's behaviour exactly: the most recent asset of each item was
    # the one that would have been published, so it becomes the selection.
    # `created_at, id` matches the service's ordering, ties included.
    op.execute(
        """
        INSERT INTO content_item_media (id, content_item_id, media_asset_id, position)
        SELECT latest.id, latest.content_item_id, latest.id, 0
        FROM media_assets AS latest
        WHERE latest.content_item_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM media_assets AS newer
            WHERE newer.content_item_id = latest.content_item_id
              AND (newer.created_at, newer.id) > (latest.created_at, latest.id)
          )
        """
    )

    # ── 3. what each attempt actually published ──
    op.create_table(
        "content_publication_media",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "publication_id",
            sa.Uuid(),
            sa.ForeignKey("content_publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_asset_id",
            sa.Uuid(),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_content_publication_media_pub_position",
        "content_publication_media",
        ["publication_id", "position"],
    )
    op.execute(
        """
        INSERT INTO content_publication_media
            (id, publication_id, media_asset_id, position)
        SELECT id, id, content_image_id, 0
        FROM content_publications
        WHERE content_image_id IS NOT NULL
        """
    )

    # ── 4. drop what the new tables replace ──
    with op.batch_alter_table("content_publications") as batch:
        batch.drop_column("content_image_id")
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_column("content_item_id")


def downgrade() -> None:
    """Reverse the split. Lossy by nature, and deliberately so.

    A schema with one image per item and one per publication has nowhere to put
    a second selected image, so everything past the first is dropped rather
    than silently reinterpreted.
    """
    connection = op.get_bind()
    is_postgres = connection.dialect.name == "postgresql"

    with op.batch_alter_table("media_assets") as batch:
        batch.add_column(sa.Column("content_item_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE media_assets SET content_item_id = ("
        "SELECT content_item_media.content_item_id FROM content_item_media "
        "WHERE content_item_media.media_asset_id = media_assets.id "
        "ORDER BY content_item_media.position LIMIT 1)"
    )
    # An asset nobody selected has no item to go back to, and the column was
    # NOT NULL before this revision.
    op.execute("DELETE FROM media_assets WHERE content_item_id IS NULL")

    with op.batch_alter_table("content_publications") as batch:
        batch.add_column(sa.Column("content_image_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE content_publications SET content_image_id = ("
        "SELECT content_publication_media.media_asset_id "
        "FROM content_publication_media "
        "WHERE content_publication_media.publication_id = content_publications.id "
        "ORDER BY content_publication_media.position LIMIT 1)"
    )

    op.drop_index(
        "ix_content_publication_media_pub_position",
        table_name="content_publication_media",
    )
    op.drop_table("content_publication_media")
    op.drop_index(
        "ix_content_item_media_item_position", table_name="content_item_media"
    )
    op.drop_table("content_item_media")

    op.drop_index("ix_media_assets_group_checksum", table_name="media_assets")
    op.drop_index("ix_media_assets_group_created", table_name="media_assets")

    # Generated rows always had both; an upload cannot survive a schema that
    # requires a prompt, so it is dropped rather than given a fabricated one.
    op.execute("DELETE FROM media_assets WHERE prompt IS NULL OR model IS NULL")
    with op.batch_alter_table("media_assets") as batch:
        batch.alter_column("content_item_id", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("prompt", existing_type=sa.Text(), nullable=False)
        batch.alter_column("model", existing_type=sa.Text(), nullable=False)
        batch.drop_column("alt_text")
        batch.drop_column("checksum")
        batch.drop_column("byte_size")
        batch.drop_column("height")
        batch.drop_column("width")
        batch.drop_column("mime_type")
        batch.drop_column("filename")
        batch.drop_column("source")
        batch.drop_column("generation_group")

    op.rename_table("media_assets", "content_images")
    op.create_index(
        "ix_content_images_item_created",
        "content_images",
        ["content_item_id", "created_at"],
    )
    if is_postgres:
        _media_source.drop(connection, checkfirst=True)
