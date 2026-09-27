from __future__ import annotations

from typing import TYPE_CHECKING, Any

from alembic import context
from sqlalchemy import Connection, Table, inspect, text

from stillhead._internal.foreign_keys import DIALECT as SQLITE
from stillhead._internal.foreign_keys import foreign_key_enforcement
from stillhead.errors import (
    AutocommitConnection,
    BrokenForeignKeys,
    MissingConnection,
    MissingOfflineUrl,
    OpenTransaction,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping

    from alembic.runtime.migration import MigrationContext, MigrationInfo
    from sqlalchemy.sql.schema import SchemaItem

    from stillhead._internal.module import ValidatedModule


def run_migrations(module: ValidatedModule) -> None:
    """Run the migrations of the module. Without a connection, run offline."""
    connection: object = context.config.attributes.get("connection")
    if connection is None:
        return _run_offline(module)
    return _run_online(module, connection)


def comparison_options(module: ValidatedModule) -> dict[str, Any]:
    """Return the settings for each comparison of the models with the database.

    Migrations and tests must compare in the same way, so both use these.
    Nothing is qualified with a schema.
    """
    return {
        "target_metadata": module.metadata,
        "version_table": module.version_table,
        "version_table_schema": None,
        "include_schemas": False,
        "include_name": include_name_for(module),
        "include_object": include_object_for(module),
        "compare_type": True,
        "compare_server_default": True,
    }


def include_name_for(module: ValidatedModule) -> Callable[..., bool]:
    """Return a filter that keeps only the database tables that the module owns.

    Without it, autogenerate drops the tables of other modules.
    """

    def include_name(
        name: str | None,
        type_: str,
        parent_names: Mapping[str, str | None],
    ) -> bool:
        if type_ == "schema":
            # None is the schema of the search path.
            return name is None
        if type_ == "table":
            return module.owns_table(name)
        return True

    return include_name


def include_object_for(module: ValidatedModule) -> Callable[..., bool]:
    """Return a filter that keeps only the tables that the module owns.

    It filters the models as well as the database. Without it, autogenerate
    creates the tables of other modules.
    """

    def include_object(
        object_: SchemaItem,
        name: str | None,
        type_: str,
        reflected: bool,
        compare_to: object | None,
    ) -> bool:
        if isinstance(object_, Table):
            return module.owns_table(object_.name)
        return True

    return include_object


def _run_online(module: ValidatedModule, connection: object) -> None:
    if not isinstance(connection, Connection):
        raise MissingConnection(connection)

    # Alembic does not commit a transaction that was open before it started.
    if connection.in_transaction():
        raise OpenTransaction(at_end_of_block=False)
    if _is_autocommit(connection):
        raise AutocommitConnection

    # SQLite changes a table by dropping it. Foreign key checks block the drop.
    with foreign_key_enforcement(connection, enabled=False):
        context.configure(
            connection=connection,
            # Runs inside the transaction of each revision, before its commit.
            on_version_apply=(
                _foreign_key_check_for(module, connection)
                if connection.dialect.name == SQLITE
                else None
            ),
            # SQLite cannot alter most columns, so Alembic copies the table.
            render_as_batch=connection.dialect.name == SQLITE,
            **comparison_options(module),
        )

        with context.begin_transaction():
            context.run_migrations()


def _foreign_key_check_for(
    module: ValidatedModule, connection: Connection
) -> Callable[
    [MigrationContext, MigrationInfo, Collection[Any], Mapping[str, Any]], None
]:
    """Return a check that raises when a table of the module has a row whose parent is missing.

    SQLite does not check foreign keys during a migration, so this checks them
    after each revision.
    """

    def check(
        ctx: MigrationContext,
        step: MigrationInfo,
        heads: Collection[Any],
        run_args: Mapping[str, Any],
    ) -> None:
        # One table at a time: a check of the whole database fails on a
        # malformed foreign key of another module.
        quote = connection.dialect.identifier_preparer.quote
        owned = [
            name
            for name in inspect(connection).get_table_names()
            if module.owns_table(name)
        ]
        broken = sorted(
            {
                (row[0], row[2])
                for name in owned
                for row in connection.execute(
                    text(f"PRAGMA foreign_key_check({quote(name)})")
                )
            }
        )
        if broken:
            raise BrokenForeignKeys(module.name, broken)

    return check


def _is_autocommit(connection: Connection) -> bool:
    """Return True when the driver connection commits each statement itself."""
    driver = connection.connection.dbapi_connection
    if getattr(driver, "autocommit", None) is True:
        return True
    return (
        connection.dialect.name == SQLITE
        and getattr(driver, "isolation_level", "") is None
    )


def _run_offline(module: ValidatedModule) -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    if not url:
        raise MissingOfflineUrl

    context.configure(
        url=url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **comparison_options(module),
    )

    # Offline, there is no connection. The SQL sets the search path itself.
    schema: object = context.config.attributes.get("schema")

    with context.begin_transaction():
        if isinstance(schema, str):
            context.execute(f'SET search_path TO "{schema}"')
        context.run_migrations()
