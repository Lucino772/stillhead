"""beta: initial

Revision ID: 0001_beta
Revises:
Create Date: 2026-08-04 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_beta"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "beta_other",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("thing_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("beta_other")
