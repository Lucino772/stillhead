from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import inspect, select, text

from stillhead import apply_pending, commands, use_schema
from stillhead.errors import InvalidSchemaName, OpenTransaction
from stillhead.testing import (
    assert_migrations_match_models,
    empty_namespaces,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection, Engine

    from stillhead import ValidatedModule

pytestmark = pytest.mark.integration


@pytest.fixture
def two_schemas(postgres: Engine) -> Engine:
    with postgres.begin() as connection:
        for schema in ("tenant_a", "tenant_b"):
            connection.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            connection.execute(text(f"CREATE SCHEMA {schema}"))
    return postgres


def _search_path(connection: Connection) -> str:
    """Read the search path, and end the transaction that the read starts."""
    value = connection.execute(text("SHOW search_path")).scalar_one()
    connection.rollback()
    return value


def _tables_in(postgres: Engine, schema: str) -> set[str]:
    with postgres.connect() as connection:
        return set(inspect(connection).get_table_names(schema=schema))


# --- What it refuses --------------------------------------------------------


@pytest.mark.parametrize("schema", ["Orders", "1orders", "or-ders", "", "a b"])
def test_refuses_a_name_that_is_not_safe_to_interpolate(
    schema: str, postgres: Engine
) -> None:
    with (
        postgres.connect() as connection,
        pytest.raises(InvalidSchemaName),
        use_schema(connection, schema),
    ):
        pass


def test_refuses_a_name_that_would_close_the_quoting(postgres: Engine) -> None:
    with (
        postgres.connect() as connection,
        pytest.raises(InvalidSchemaName),
        use_schema(connection, 'public"; DROP SCHEMA "orders'),
    ):
        pass


# --- What it does -----------------------------------------------------------


def test_migrations_land_in_the_schema_the_block_names(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    apply_pending([notes], two_schemas, schema="tenant_a")

    assert _tables_in(two_schemas, "tenant_a") == {
        "notes_note",
        "notes_alembic_version",
    }
    assert _tables_in(two_schemas, "tenant_b") == set()


def test_the_same_modules_serve_two_schemas_independently(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    for schema in ("tenant_a", "tenant_b"):
        apply_pending([notes], two_schemas, schema=schema)

    for schema in ("tenant_a", "tenant_b"):
        assert "notes_note" in _tables_in(two_schemas, schema)

    with two_schemas.connect() as connection, use_schema(connection, "tenant_a"):
        assert commands.database_revision(notes, connection) == "0001_notes"


def test_the_setting_is_restored_and_siblings_are_untouched(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    with two_schemas.connect() as connection:
        before = _search_path(connection)

        with use_schema(connection, "tenant_a"):
            assert _search_path(connection) == "tenant_a"

        assert _search_path(connection) == before

    with two_schemas.connect() as sibling:
        assert _search_path(sibling) != "tenant_a"


def test_the_setting_is_restored_after_a_failure(two_schemas: Engine) -> None:
    with two_schemas.connect() as connection:
        before = _search_path(connection)

        with pytest.raises(ZeroDivisionError), use_schema(connection, "tenant_a"):
            _ = 1 / 0

        assert _search_path(connection) == before


def test_the_setting_survives_the_commits_a_migration_makes(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    with two_schemas.connect() as connection, use_schema(connection, "tenant_a"):
        commands.upgrade(notes, connection)
        connection.commit()

        assert _search_path(connection) == "tenant_a"

    assert "notes_note" in _tables_in(two_schemas, "tenant_a")


def test_autogenerate_agrees_with_the_models_inside_the_schema(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    with empty_namespaces([notes], two_schemas, "tenant_a"):
        assert_migrations_match_models(notes, two_schemas, "tenant_a")


def test_a_table_outside_the_schema_is_invisible(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    with two_schemas.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS public.notes_note"))
        connection.execute(
            text("CREATE TABLE public.notes_note (id varchar(36) primary key)")
        )

    try:
        apply_pending([notes], two_schemas, schema="tenant_a")
        assert_migrations_match_models(notes, two_schemas, "tenant_a")
    finally:
        with two_schemas.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS public.notes_note"))


def test_a_command_refuses_an_uncommitted_search_path(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    """Ending that transaction would undo the search path, and migrate the wrong schema."""
    with two_schemas.connect() as connection:
        connection.execute(text("SET search_path TO tenant_a"))

        with pytest.raises(OpenTransaction):
            commands.upgrade(notes, connection)

        assert connection.execute(text("SHOW search_path")).scalar_one() == "tenant_a"

    assert _tables_in(two_schemas, "tenant_a") == set()
    assert "notes_note" not in _tables_in(two_schemas, "public")


def test_the_block_refuses_a_connection_with_an_open_transaction(
    two_schemas: Engine,
) -> None:
    with two_schemas.connect() as connection:
        connection.execute(text("SELECT 1"))

        with pytest.raises(OpenTransaction), use_schema(connection, "tenant_a"):
            pass

        assert connection.in_transaction()


def test_the_block_rolls_back_and_reports_an_open_transaction(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    apply_pending([notes], two_schemas, schema="tenant_a")
    note = notes.metadata.tables["notes_note"]

    with two_schemas.connect() as connection:
        before = _search_path(connection)

        with pytest.raises(OpenTransaction), use_schema(connection, "tenant_a"):
            connection.execute(note.insert(), [{"id": "n1", "body": "left open"}])

        assert _search_path(connection) == before
        with use_schema(connection, "tenant_a"):
            assert connection.execute(select(note.c.id)).all() == []
            connection.rollback()


def test_the_block_reports_a_read_that_is_left_open(
    notes: ValidatedModule, two_schemas: Engine
) -> None:
    apply_pending([notes], two_schemas, schema="tenant_a")
    note = notes.metadata.tables["notes_note"]

    with (
        two_schemas.connect() as connection,
        pytest.raises(OpenTransaction),
        use_schema(connection, "tenant_a"),
    ):
        connection.execute(select(note.c.id)).all()
