"""sync: initial

Revision ID: 0001_sync
Revises:
Create Date: 2026-08-04 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_sync"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_source",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sync_link",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("remote_id", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sync_source.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sync_link")
    op.drop_table("sync_source")
