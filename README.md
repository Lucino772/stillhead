# stillhead

Per-module database migrations on Alembic: each module owns its namespace, its version table and its revision lineage — so two people never touch the same chain.

An alembic is the cap of a pot still, and the still head is the piece above it that takes the rising vapour and decides where each fraction goes. This package sits on Alembic and does the same thing to one database: separates it into modules that each own their tables, and keeps their lineages from ever crossing.

## Status

Early. The package body has not landed yet.
