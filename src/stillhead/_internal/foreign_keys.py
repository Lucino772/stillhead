from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from stillhead.errors import NoDriverConnection

if TYPE_CHECKING:
    from collections.abc import Generator

    from sqlalchemy import Connection

DIALECT = "sqlite"


@contextmanager
def foreign_key_enforcement(
    connection: Connection, *, enabled: bool
) -> Generator[None]:
    """Turn SQLite foreign key checks on or off during the block.

    Sets the previous value again after the block. Does nothing on other
    databases. Commits when the block starts and when it ends.
    """
    if connection.dialect.name != DIALECT:
        yield
        return

    previous = _set_foreign_keys(connection, enabled=enabled)
    try:
        yield
    finally:
        _set_foreign_keys(connection, enabled=previous)


def _set_foreign_keys(connection: Connection, *, enabled: bool) -> bool:
    """Set the pragma, and return the previous value.

    SQLite ignores the pragma inside a transaction. So this commits first, and
    uses the driver connection directly.
    """
    connection.commit()

    driver_connection = connection.connection.dbapi_connection
    if driver_connection is None:
        raise NoDriverConnection

    cursor = driver_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys")
        row = cursor.fetchone()
        previous = bool(row[0]) if row is not None else False
        cursor.execute(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")
    finally:
        cursor.close()

    return previous
