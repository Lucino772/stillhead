from __future__ import annotations

import re
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text

from stillhead.errors import InvalidSchemaName, OpenTransaction, SchemaNotSupported

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Connection

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")

_UNSUPPORTED = "sqlite"


def check_schema(schema: str, dialect: str) -> None:
    """Raise an error when the database cannot use the schema.

    Raises on SQLite, and for a schema name that is not a lowercase identifier.
    """
    if dialect == _UNSUPPORTED:
        raise SchemaNotSupported(schema)

    if not _IDENTIFIER.match(schema):
        raise InvalidSchemaName(schema, _IDENTIFIER.pattern)


@contextmanager
def use_schema(connection: Connection, schema: str) -> Generator[None]:
    """Set the search path of the connection to one schema, during the block.

    The connection must have no open transaction when the block starts. End
    your transactions inside the block: a transaction that is still open when
    the block ends is rolled back, and an error is raised. After the block, sets
    the previous search path again.

    Raises an error on SQLite, and for a schema name that is not a lowercase
    identifier.
    """
    check_schema(schema, connection.dialect.name)

    if connection.in_transaction():
        raise OpenTransaction(at_end_of_block=False)
    # Postgres gives the path in a form that it accepts back. Do not quote it.
    previous = connection.execute(text("SHOW search_path")).scalar_one()
    connection.execute(text(f'SET search_path TO "{schema}"'))
    connection.commit()

    try:
        yield
    except BaseException:
        connection.rollback()
        connection.execute(text(f"SET search_path TO {previous}"))
        connection.commit()
        raise

    left_open = connection.in_transaction()
    connection.rollback()
    connection.execute(text(f"SET search_path TO {previous}"))
    connection.commit()
    if left_open:
        raise OpenTransaction(at_end_of_block=True)
