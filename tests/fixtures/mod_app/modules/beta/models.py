from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table

metadata = MetaData()

other = Table(
    "beta_other",
    metadata,
    Column("id", String(36), primary_key=True),
    # A plain column, not a foreign key to another module.
    Column("thing_id", String(36), nullable=False),
    Column("note", String(200), nullable=False),
)
