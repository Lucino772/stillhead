from __future__ import annotations

from sqlalchemy import Column, ForeignKey, MetaData, String, Table

metadata = MetaData()

source = Table(
    "sync_source",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("label", String(200), nullable=False),
)

# A foreign key between two tables of this module.
link = Table(
    "sync_link",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("source_id", String(36), ForeignKey(source.c.id), nullable=False),
    Column("remote_id", String(200), nullable=False),
)
