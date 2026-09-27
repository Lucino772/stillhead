from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, text

from stillhead._internal.commands import upgrade
from stillhead._internal.foreign_keys import foreign_key_enforcement
from stillhead._internal.schemas import use_schema
from stillhead._internal.validation import validate_module_set
from stillhead.env import comparison_options
from stillhead.errors import MigrationsDriftedFromModels

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Sequence

    from sqlalchemy import Engine

    from stillhead._internal.module import ModuleMigrations, ValidatedModule


def assert_migrations_match_models(
    module: ValidatedModule,
    engine: Engine,
    schema: str | None = None,
) -> None:
    """Apply every revision, then check that the database matches the models.

    Use it on empty namespaces. A table that another test left can hide a
    difference.
    """
    with ExitStack() as stack:
        connection = stack.enter_context(engine.connect())
        if schema is not None:
            stack.enter_context(use_schema(connection, schema))

        upgrade(module, connection)
        difference = compare_metadata(
            MigrationContext.configure(
                connection=connection,
                opts=comparison_options(module),
            ),
            module.metadata,
        )
        connection.rollback()

    if difference:
        raise MigrationsDriftedFromModels(module.name, difference)


@contextmanager
def empty_namespaces(
    modules: Iterable[ModuleMigrations],
    engine: Engine,
    schema: str | None = None,
) -> Generator[None]:
    """Drop the tables of the modules before the block and after it.

    Drops only the tables that the modules own. Does not drop the schema.
    """
    validated = validate_module_set(modules)

    _drop_owned_tables(validated, engine, schema)
    try:
        yield
    finally:
        _drop_owned_tables(validated, engine, schema)


def _drop_owned_tables(
    modules: Sequence[ValidatedModule],
    engine: Engine,
    schema: str | None = None,
) -> None:
    """Drop each table that one of the modules owns, in any order.

    Gets the table names without reflection: reflection fails when a foreign
    key points to a table that is already dropped. Turns the foreign key
    checks off during the drops.
    """
    with ExitStack() as stack:
        connection = stack.enter_context(engine.connect())
        if schema is not None:
            stack.enter_context(use_schema(connection, schema))
        stack.enter_context(foreign_key_enforcement(connection, enabled=False))

        owned = [
            name
            for name in inspect(connection).get_table_names()
            if any(module.owns_table(name) for module in modules)
        ]
        quote = connection.dialect.identifier_preparer.quote
        cascade = " CASCADE" if connection.dialect.name == "postgresql" else ""
        for name in owned:
            connection.execute(text(f"DROP TABLE IF EXISTS {quote(name)}{cascade}"))
        connection.commit()
