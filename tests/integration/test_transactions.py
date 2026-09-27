from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

from stillhead import commands
from stillhead.errors import AutocommitConnection, OpenTransaction

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from stillhead import ValidatedModule

pytestmark = pytest.mark.integration


def test_a_command_refuses_an_open_transaction_and_leaves_it_alone(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    note = notes.metadata.tables["notes_note"]
    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)

    with prefix_engine.connect() as connection:
        connection.execute(note.insert(), [{"id": "n1", "body": "not committed"}])

        with pytest.raises(OpenTransaction):
            commands.upgrade(sync, connection)

        assert connection.in_transaction()
        assert connection.execute(select(note.c.id)).scalars().all() == ["n1"]

        connection.rollback()
        assert connection.execute(select(note.c.id)).all() == []
        assert commands.database_revision(sync, connection) is None


def test_a_command_refuses_an_open_read_transaction(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    note = notes.metadata.tables["notes_note"]
    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)

    with prefix_engine.connect() as connection:
        connection.execute(select(note.c.id)).all()

        with pytest.raises(OpenTransaction):
            commands.upgrade(notes, connection)


def test_reading_with_stillhead_then_upgrading_works(
    sync: ValidatedModule, prefix_engine: Engine
) -> None:
    with prefix_engine.connect() as connection:
        assert commands.pending_revisions(sync, connection) == ("0001_sync",)
        assert not connection.in_transaction()

        commands.upgrade(sync, connection)

        assert commands.database_revision(sync, connection) == "0001_sync"


def test_a_read_command_leaves_an_open_transaction_open(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    with prefix_engine.connect() as connection:
        connection.execute(select(1)).all()

        commands.database_revision(notes, connection)

        assert connection.in_transaction()


def test_a_command_refuses_an_autocommit_connection(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    autocommit = prefix_engine.execution_options(isolation_level="AUTOCOMMIT")

    with autocommit.connect() as connection, pytest.raises(AutocommitConnection):
        commands.upgrade(notes, connection)
