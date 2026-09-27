from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table

metadata = MetaData()

thing = Table(
    "alpha_thing",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("label", String(200), nullable=False),
)
