"""notes: initial

Revision ID: 0001_notes
Revises:
Create Date: 2026-08-04 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_notes"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "notes_note",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("notes_note")
