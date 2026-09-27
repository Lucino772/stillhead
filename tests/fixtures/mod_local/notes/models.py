from __future__ import annotations

from sqlalchemy import Column, MetaData, String, Table

metadata = MetaData()

note = Table(
    "notes_note",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("body", String(2000), nullable=False),
)
