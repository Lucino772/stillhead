from __future__ import annotations

import argparse
import importlib
import os
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

from alembic.util import CommandError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from stillhead import commands
from stillhead._internal.module import ModuleMigrations, ValidatedModule
from stillhead._internal.schemas import use_schema
from stillhead._internal.validation import validate_module
from stillhead.errors import (
    MalformedModuleReference,
    MissingDatabaseUrl,
    ModuleAttributeNotFound,
    NoModulesNamed,
    NotAModuleMigrations,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from sqlalchemy import Connection


DATABASE_URL_VARIABLE = "STILLHEAD_DATABASE_URL"

MODULE_HELP = "import path of the module definition, as package.module:ATTRIBUTE"

SCHEMA_HELP = "schema to use; the default schema of the database when omitted"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)

    command_name: str = arguments.command

    try:
        if command_name == "status":
            return _status(arguments)
        if command_name == "upgrade":
            return _upgrade(arguments)
        if command_name == "downgrade":
            return _downgrade(arguments)
        if command_name == "revision":
            return _revision(arguments)
        return _current(arguments)
    except (
        RuntimeError,
        ValueError,
        KeyError,
        ImportError,
        NotAModuleMigrations,
        CommandError,
        SQLAlchemyError,
    ) as error:
        print(f"stillhead: {error}", file=sys.stderr)
        return 1


def load_module(reference: str) -> ValidatedModule:
    """Import a module definition from package.module:ATTRIBUTE, and validate it."""
    module_path, separator, attribute = reference.partition(":")
    if not separator or not module_path or not attribute:
        raise MalformedModuleReference(reference)

    imported = importlib.import_module(module_path)
    if not hasattr(imported, attribute):
        raise ModuleAttributeNotFound(reference)
    loaded: object = getattr(imported, attribute)
    if not isinstance(loaded, ModuleMigrations):
        raise NotAModuleMigrations(reference, loaded)

    return validate_module(loaded)


@contextmanager
def _connection(arguments: argparse.Namespace) -> Generator[Connection]:
    """Open a connection that uses the schema from the command line."""
    with create_engine(_database_url()).connect() as connection:
        schema: str | None = arguments.schema
        if schema is None:
            yield connection
            return
        with use_schema(connection, schema):
            yield connection


def _upgrade(arguments: argparse.Namespace) -> int:
    module = load_module(arguments.module)

    if arguments.sql:
        commands.emit_upgrade_sql(
            module, _database_url(), arguments.revision, arguments.schema
        )
        return 0

    with _connection(arguments) as connection:
        commands.upgrade(module, connection, arguments.revision)
    return 0


def _downgrade(arguments: argparse.Namespace) -> int:
    module = load_module(arguments.module)
    with _connection(arguments) as connection:
        commands.downgrade(module, connection, arguments.revision)
    return 0


def _revision(arguments: argparse.Namespace) -> int:
    module = load_module(arguments.module)

    if not arguments.autogenerate:
        commands.create_revision(module, arguments.message)
        return 0

    with _connection(arguments) as connection:
        commands.create_revision(
            module,
            arguments.message,
            connection=connection,
            autogenerate=True,
        )
    return 0


def _current(arguments: argparse.Namespace) -> int:
    module = load_module(arguments.module)
    with _connection(arguments) as connection:
        print(commands.database_revision(module, connection) or "(none)")
    return 0


def _status(arguments: argparse.Namespace) -> int:
    """Print one line for each module: its stamp, its head, its pending count."""
    references: list[str] = arguments.module or []
    if not references:
        raise NoModulesNamed

    # The modules are not checked together: status reports on any modules.
    modules = [load_module(reference) for reference in references]

    with _connection(arguments) as connection:
        for module in sorted(modules, key=lambda named: named.name):
            print(
                format_status_line(
                    module.name,
                    applied=commands.database_revision(module, connection),
                    head=commands.script_head(module),
                    pending=len(commands.pending_revisions(module, connection)),
                )
            )
    return 0


def format_status_line(
    name: str,
    applied: str | None,
    head: str | None,
    pending: int,
) -> str:
    """Format one line of the status output."""
    state = "up to date" if not pending else f"{pending} pending"
    applied_or_none = applied or "(none)"
    head_or_none = head or "(none)"

    return f"{name:<12} db={applied_or_none:<16} head={head_or_none:<16} {state}"


def _database_url() -> str:
    """Return the database URL from the environment."""
    url = os.environ.get(DATABASE_URL_VARIABLE)
    if not url:
        raise MissingDatabaseUrl(DATABASE_URL_VARIABLE)
    return url


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stillhead",
        description="Run the migrations of one module.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    def subcommand(name: str, summary: str) -> argparse.ArgumentParser:
        created = subcommands.add_parser(name, help=summary)
        created.add_argument("--schema", default=None, help=SCHEMA_HELP)
        return created

    upgrade = subcommand("upgrade", "apply pending revisions")
    upgrade.add_argument("--module", required=True, help=MODULE_HELP)
    upgrade.add_argument("--revision", default="head")
    upgrade.add_argument(
        "--sql",
        action="store_true",
        help="print the DDL instead of running it",
    )

    downgrade = subcommand("downgrade", "revert to a revision")
    downgrade.add_argument("--module", required=True, help=MODULE_HELP)
    downgrade.add_argument("--revision", required=True)

    revision = subcommand("revision", "create a revision file")
    revision.add_argument("--module", required=True, help=MODULE_HELP)
    revision.add_argument("-m", "--message", required=True)
    revision.add_argument("--autogenerate", action="store_true")

    status = subcommand("status", "head vs database, per module")
    # Not required: the missing-module error shows the reference format.
    status.add_argument(
        "--module", action="append", help=f"{MODULE_HELP}; repeat per module"
    )

    current = subcommand("current", "the database's revision")
    current.add_argument("--module", required=True, help=MODULE_HELP)

    return parser


if __name__ == "__main__":  # pragma: no cover - console script entry point
    raise SystemExit(main())
