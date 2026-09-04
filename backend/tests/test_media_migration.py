"""Migration 0008 against a seeded database, both directions.

The interesting property is not that the tables appear — it is that the
*implicit* behaviour survives the move. Before this revision, publishing sent
whichever image was most recent, with nothing recorded anywhere saying so. The
migration has to turn that into an explicit ``content_item_media`` row pointing
at the same image, or every existing post silently changes what it would send.

**Why the pre-0008 schema is built by hand here.** Revisions 0001–0006 declare
``postgresql.JSONB`` columns directly, which SQLite cannot compile, so the chain
cannot be replayed off Postgres. Those revisions have already run in production;
0008 has not, and it is the one worth a test. So the test creates only the four
tables 0008 touches, stamps the revision before it, and exercises the upgrade
and the downgrade against that. Everything 0008 does is wrapped in
``batch_alter_table``, which is what makes running it here possible at all.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]

BEFORE = "0007_in_flight_publish_index"
AFTER = "0008_media_assets"

# The pre-0008 shape of the tables 0008 rewrites, in portable DDL. Only the
# columns the migration reads or moves are present — a faithful copy of every
# column would be a second, drifting definition of a schema that no longer
# exists in the models.
_BEFORE_SCHEMA = (
    """
    CREATE TABLE users (
        id CHAR(32) NOT NULL PRIMARY KEY,
        email TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE content_items (
        id CHAR(32) NOT NULL PRIMARY KEY,
        platform VARCHAR(9) NOT NULL,
        generation_group CHAR(32),
        variant_style TEXT NOT NULL,
        generated_body TEXT NOT NULL,
        status VARCHAR(16) NOT NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE content_images (
        id CHAR(32) NOT NULL PRIMARY KEY,
        content_item_id CHAR(32) NOT NULL
            REFERENCES content_items (id) ON DELETE CASCADE,
        prompt TEXT NOT NULL,
        model TEXT NOT NULL,
        data BLOB NOT NULL,
        created_by CHAR(32) REFERENCES users (id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX ix_content_images_item_created "
    "ON content_images (content_item_id, created_at)",
    """
    CREATE TABLE content_publications (
        id CHAR(32) NOT NULL PRIMARY KEY,
        content_item_id CHAR(32) NOT NULL
            REFERENCES content_items (id) ON DELETE CASCADE,
        social_account_id CHAR(32),
        content_image_id CHAR(32)
            REFERENCES content_images (id) ON DELETE SET NULL,
        status VARCHAR(9) NOT NULL,
        external_post_id TEXT,
        permalink TEXT,
        request_summary JSON,
        error TEXT,
        error_code TEXT,
        attempted_by CHAR(32) REFERENCES users (id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )
    """,
)


@pytest.fixture
def migrated(tmp_path):
    """A SQLite database holding the pre-0008 schema, stamped at 0007."""
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        for statement in _BEFORE_SCHEMA:
            conn.execute(text(statement))

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    command.stamp(config, BEFORE)
    try:
        yield config, engine
    finally:
        engine.dispose()


def _seed(engine) -> dict[str, uuid.UUID]:
    """One item, three images, and a publication naming the middle one."""
    ids = {
        key: uuid.uuid4()
        for key in ("item", "group", "old", "middle", "newest", "publication")
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO content_items "
                "(id, platform, generation_group, variant_style, generated_body, "
                " status, created_at, updated_at) "
                "VALUES (:id, 'facebook', :grp, 'direct', 'body', 'approved', "
                "        '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            ),
            {"id": ids["item"].hex, "grp": ids["group"].hex},
        )
        for key, stamp in (
            ("old", "2026-01-01 00:00:00"),
            ("middle", "2026-01-02 00:00:00"),
            ("newest", "2026-01-03 00:00:00"),
        ):
            conn.execute(
                text(
                    "INSERT INTO content_images "
                    "(id, content_item_id, prompt, model, data, created_at) "
                    "VALUES (:id, :item, :prompt, 'mock', :data, :created)"
                ),
                {
                    "id": ids[key].hex,
                    "item": ids["item"].hex,
                    "prompt": f"the {key} image",
                    # Deliberately not a real image: the backfill must record
                    # unknown dimensions rather than fail the whole migration.
                    "data": b"not-a-real-png",
                    "created": stamp,
                },
            )
        conn.execute(
            text(
                "INSERT INTO content_publications "
                "(id, content_item_id, content_image_id, status, created_at) "
                "VALUES (:id, :item, :image, 'succeeded', '2026-01-04 00:00:00')"
            ),
            {
                "id": ids["publication"].hex,
                "item": ids["item"].hex,
                "image": ids["middle"].hex,
            },
        )
    return ids


def test_upgrade_preserves_the_image_publishing_would_have_used(migrated) -> None:
    config, engine = migrated
    ids = _seed(engine)

    command.upgrade(config, AFTER)

    with engine.connect() as conn:
        selection = conn.execute(
            text(
                "SELECT media_asset_id, position FROM content_item_media "
                "WHERE content_item_id = :item"
            ),
            {"item": ids["item"].hex},
        ).fetchall()

    # Exactly the image the old implicit rule would have sent, and only that
    # one: the other two stay in the library, unattached.
    assert len(selection) == 1
    assert uuid.UUID(hex=selection[0][0]) == ids["newest"]
    assert selection[0][1] == 0


def test_upgrade_keeps_publications_pointing_at_their_bytes(migrated) -> None:
    config, engine = migrated
    ids = _seed(engine)

    command.upgrade(config, AFTER)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT media_asset_id, position FROM content_publication_media "
                "WHERE publication_id = :pub"
            ),
            {"pub": ids["publication"].hex},
        ).fetchall()
        # The ids survive the rename, which is the whole reason 0008 renames
        # the table rather than recreating it.
        exists = conn.execute(
            text("SELECT count(*) FROM media_assets WHERE id = :id"),
            {"id": ids["middle"].hex},
        ).scalar()

    assert len(rows) == 1
    assert uuid.UUID(hex=rows[0][0]) == ids["middle"]
    assert exists == 1


def test_upgrade_backfills_the_descriptive_columns(migrated) -> None:
    config, engine = migrated
    ids = _seed(engine)

    command.upgrade(config, AFTER)

    with engine.connect() as conn:
        source, mime, group, byte_size, checksum, width = conn.execute(
            text(
                "SELECT source, mime_type, generation_group, byte_size, "
                "       checksum, width FROM media_assets WHERE id = :id"
            ),
            {"id": ids["old"].hex},
        ).one()

    assert source == "generated"
    assert mime == "image/png"
    assert uuid.UUID(hex=group) == ids["group"]
    assert byte_size == len(b"not-a-real-png")
    assert len(checksum) == 64  # sha256 hex
    # Unreadable bytes backfill as unknown rather than failing the migration.
    assert width == 0


def test_downgrade_restores_the_old_shape(migrated) -> None:
    config, engine = migrated
    ids = _seed(engine)
    command.upgrade(config, AFTER)

    command.downgrade(config, BEFORE)

    with engine.connect() as conn:
        image_owner = conn.execute(
            text("SELECT content_item_id FROM content_images WHERE id = :id"),
            {"id": ids["newest"].hex},
        ).scalar()
        publication_image = conn.execute(
            text("SELECT content_image_id FROM content_publications WHERE id = :id"),
            {"id": ids["publication"].hex},
        ).scalar()
        # Lossy by design: the two images nobody selected have nowhere to live
        # in a schema where an image belongs to exactly one item.
        remaining = conn.execute(text("SELECT count(*) FROM content_images")).scalar()

    assert uuid.UUID(hex=image_owner) == ids["item"]
    assert uuid.UUID(hex=publication_image) == ids["middle"]
    assert remaining == 1
