"""courses / course_offerings / scraper_runs (Fase 1).

Revision ID: 0002_catalog
Revises: 0001_initial
Create Date: 2026-07-10
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_catalog"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_scraper_run_status = sa.Enum(
    "running", "pending", "approved", "rejected", "failed", name="scraperrunstatus"
)


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("course_code", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_accredited", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
    op.create_table(
        "course_offerings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "course_id",
            sa.Uuid(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offering_code", sa.Text(), nullable=False, unique=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
        sa.Column("gst", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("places_available", sa.Integer(), nullable=True),
        sa.Column("places_text", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("finish_date", sa.Date(), nullable=True),
        sa.Column("time_text", sa.Text(), nullable=True),
        sa.Column("session_count", sa.Integer(), nullable=True),
        sa.Column("session_hours", sa.Numeric(6, 2), nullable=True),
        sa.Column("enrollment_url", sa.Text(), nullable=True),
        sa.Column("detail_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
        "ix_course_offerings_course_id", "course_offerings", ["course_id"]
    )
    op.create_table(
        "scraper_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", _scraper_run_status, nullable=False),
        sa.Column("courses_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("offerings_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("changeset", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
    )


def downgrade() -> None:
    op.drop_table("scraper_runs")
    op.drop_index("ix_course_offerings_course_id", table_name="course_offerings")
    op.drop_table("course_offerings")
    op.drop_table("courses")
    _scraper_run_status.drop(op.get_bind(), checkfirst=True)
