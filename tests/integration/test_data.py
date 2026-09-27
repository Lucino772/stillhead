from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import String, inspect, select, text
from sqlalchemy.exc import IntegrityError

from stillhead import commands, define_module, use_schema, validate_module
from stillhead.errors import BrokenForeignKeys
from tests.integration.conftest import enforcing_foreign_keys

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy import Connection, Engine

    from stillhead import ValidatedModule

pytestmark = pytest.mark.integration

FIRST = "0001_sync"
SECOND = "0002_sync_wider_label"

_WIDER_LABEL = f'''"""sync: a wider label.

Revision ID: {SECOND}
Revises: {FIRST}
Create Date: 2026-09-27 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "{SECOND}"
down_revision: str | None = "{FIRST}"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sync_source") as batch:
        batch.alter_column(
            "label",
            existing_type=sa.String(200),
            type_=sa.String(400),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("sync_source") as batch:
        batch.alter_column(
            "label",
            existing_type=sa.String(400),
            type_=sa.String(200),
            existing_nullable=False,
        )
'''


@pytest.fixture
def sync_with_two_revisions(sync: ValidatedModule, tmp_path: Path) -> ValidatedModule:
    """The sync module with a second revision that changes a referenced table.

    On SQLite, the change rebuilds the table.
    """
    versions = tmp_path / "versions"
    versions.mkdir()
    for revision in sync.versions_path.glob("*.py"):
        shutil.copy(revision, versions / revision.name)
    (versions / f"{SECOND}.py").write_text(_WIDER_LABEL)

    return validate_module(
        define_module(name="sync", metadata=sync.metadata, versions_path=versions)
    )


@pytest.fixture
def tenant(postgres: Engine) -> Iterator[str]:
    schema = "data_tenant"
    with postgres.begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    yield schema
    with postgres.begin() as connection:
        connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))


def _migrate_with_data(connection: Connection, module: ValidatedModule) -> None:
    source = module.metadata.tables["sync_source"]
    link = module.metadata.tables["sync_link"]

    commands.upgrade(module, connection, FIRST)
    connection.execute(source.insert(), [{"id": "s1", "label": "first"}])
    connection.execute(
        link.insert(), [{"id": "l1", "source_id": "s1", "remote_id": "r1"}]
    )
    connection.commit()

    commands.upgrade(module, connection)

    joined = select(link.c.id, source.c.label).join(
        source, link.c.source_id == source.c.id
    )
    assert connection.execute(joined).all() == [("l1", "first")]
    assert commands.database_revision(module, connection) == SECOND

    label = next(
        column
        for column in inspect(connection).get_columns("sync_source")
        if column["name"] == "label"
    )
    assert isinstance(label["type"], String)
    assert label["type"].length == 400

    with pytest.raises(IntegrityError):
        connection.execute(
            link.insert(), [{"id": "l2", "source_id": "missing", "remote_id": "r2"}]
        )
    connection.rollback()


def test_rows_survive_a_migration_that_changes_a_referenced_table(
    sync_with_two_revisions: ValidatedModule, prefix_engine: Engine
) -> None:
    enforcing_foreign_keys(prefix_engine)

    with prefix_engine.connect() as connection:
        _migrate_with_data(connection, sync_with_two_revisions)


def test_rows_survive_the_same_migration_in_a_named_schema(
    sync_with_two_revisions: ValidatedModule, postgres: Engine, tenant: str
) -> None:
    with postgres.connect() as connection, use_schema(connection, tenant):
        _migrate_with_data(connection, sync_with_two_revisions)

    with postgres.connect() as connection:
        tables = set(inspect(connection).get_table_names(schema=tenant))
    assert {"sync_source", "sync_link", "sync_alembic_version"} <= tables


_ORPHANING = f'''"""sync: delete the sources and leave the links.

Revision ID: 0002_sync_orphans
Revises: {FIRST}
Create Date: 2026-09-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op

revision: str = "0002_sync_orphans"
down_revision: str | None = "{FIRST}"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM sync_source")


def downgrade() -> None:
    pass
'''


def test_a_migration_that_leaves_orphan_rows_is_refused(
    sync: ValidatedModule, sqlite_engine: Engine, tmp_path: Path
) -> None:
    enforcing_foreign_keys(sqlite_engine)
    versions = tmp_path / "versions"
    versions.mkdir()
    for revision in sync.versions_path.glob("*.py"):
        shutil.copy(revision, versions / revision.name)
    (versions / "0002_sync_orphans.py").write_text(_ORPHANING)
    module = validate_module(
        define_module(name="sync", metadata=sync.metadata, versions_path=versions)
    )
    source = module.metadata.tables["sync_source"]
    link = module.metadata.tables["sync_link"]

    with sqlite_engine.connect() as connection:
        commands.upgrade(module, connection, FIRST)
        connection.execute(source.insert(), [{"id": "s1", "label": "first"}])
        connection.execute(
            link.insert(), [{"id": "l1", "source_id": "s1", "remote_id": "r1"}]
        )
        connection.commit()

        with pytest.raises(BrokenForeignKeys, match="sync_link -> sync_source"):
            commands.upgrade(module, connection)

        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        connection.rollback()

    with sqlite_engine.connect() as connection:
        assert commands.database_revision(module, connection) == FIRST
        assert connection.execute(select(source.c.id)).scalars().all() == ["s1"]


def test_a_malformed_foreign_key_of_another_module_does_not_block(
    sync_with_two_revisions: ValidatedModule, sqlite_engine: Engine
) -> None:
    """A check of the whole database fails on it with "foreign key mismatch"."""
    with sqlite_engine.begin() as connection:
        connection.execute(text("CREATE TABLE other_parent (id INTEGER, code TEXT)"))
        connection.execute(
            text(
                "CREATE TABLE other_child (id INTEGER, "
                "code TEXT REFERENCES other_parent(code))"
            )
        )

    with sqlite_engine.connect() as connection:
        commands.upgrade(sync_with_two_revisions, connection)

        assert commands.database_revision(sync_with_two_revisions, connection) == SECOND
