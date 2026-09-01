"""Widen the anti-double-publish index to cover in-flight attempts.

Revision ID: 0007_in_flight_publish_index
Revises: 0006_publishing
Create Date: 2026-08-10

0006 guarded only `succeeded`, which stopped a duplicate from being *recorded*
but not from being *sent*: two concurrent requests could both pass the
application-level check, both insert a `pending` row, and both call the network,
leaving two live posts and an IntegrityError on whichever committed second.
Covering `pending` too makes the loser of that race fail at its INSERT, before
it can publish anything.

`failed` stays outside the index so a retry after a failure is unaffected.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007_in_flight_publish_index"
down_revision: Union[str, None] = "0006_publishing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "uq_content_publications_succeeded"
_NEW = "uq_content_publications_in_flight"


def upgrade() -> None:
    op.drop_index(_OLD, table_name="content_publications")
    op.create_index(
        _NEW,
        "content_publications",
        ["content_item_id"],
        unique=True,
        postgresql_where="status IN ('pending', 'succeeded')",
    )


def downgrade() -> None:
    op.drop_index(_NEW, table_name="content_publications")
    op.create_index(
        _OLD,
        "content_publications",
        ["content_item_id"],
        unique=True,
        postgresql_where="status = 'succeeded'",
    )
