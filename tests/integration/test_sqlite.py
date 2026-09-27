from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from stillhead import apply_pending
from stillhead._internal.cli import DATABASE_URL_VARIABLE, main
from stillhead._internal.foreign_keys import foreign_key_enforcement
from tests.integration.conftest import enforcing_foreign_keys

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from stillhead import ValidatedModule

pytestmark = pytest.mark.integration


def _populate(notes: ValidatedModule, sync: ValidatedModule, engine: Engine) -> None:
    """Insert rows on both sides of a foreign key in one module."""
    with engine.connect() as connection:
        connection.execute(
            text("INSERT INTO notes_note (id, body) VALUES ('n1', 'hi')")
        )
        connection.execute(
            text("INSERT INTO sync_source (id, label) VALUES ('s1', 'src')")
        )
        connection.execute(
            text(
                "INSERT INTO sync_link (id, source_id, remote_id) "
                "VALUES ('l1', 's1', 'r')"
            )
        )
        connection.commit()


def test_migrating_leaves_enforcement_exactly_as_it_found_it(
    notes: ValidatedModule, sqlite_engine: Engine
) -> None:
    with sqlite_engine.connect() as connection:
        before = connection.execute(text("PRAGMA foreign_keys")).scalar_one()

    apply_pending([notes], sqlite_engine)

    with sqlite_engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == before


def test_enforcement_can_be_required_for_a_block(
    notes: ValidatedModule, sqlite_engine: Engine
) -> None:
    apply_pending([notes], sqlite_engine)

    with sqlite_engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 0

        with foreign_key_enforcement(connection, enabled=True):
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1

        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 0


def test_deleting_a_parent_with_children_is_rejected(
    notes: ValidatedModule, sync: ValidatedModule, sqlite_engine: Engine
) -> None:
    enforcing_foreign_keys(sqlite_engine)
    apply_pending([notes, sync], sqlite_engine)
    _populate(notes, sync, sqlite_engine)

    with sqlite_engine.connect() as connection, pytest.raises(IntegrityError):
        connection.execute(text("DELETE FROM sync_source WHERE id = 's1'"))
        connection.commit()


def test_foreign_key_enforcement_commits_on_entry_and_on_exit(
    notes: ValidatedModule, sqlite_engine: Engine
) -> None:
    apply_pending([notes], sqlite_engine)

    with sqlite_engine.connect() as connection:
        connection.execute(text("INSERT INTO notes_note (id, body) VALUES ('in', 'x')"))
        with foreign_key_enforcement(connection, enabled=False):
            connection.execute(
                text("INSERT INTO notes_note (id, body) VALUES ('out', 'y')")
            )
        # Neither insert was committed by this test, and both survive.

    with sqlite_engine.connect() as connection:
        surviving = connection.execute(text("SELECT id FROM notes_note")).scalars()
        assert set(surviving) == {"in", "out"}


def test_the_cli_reports_a_revision_that_does_not_exist(
    notes: ValidatedModule,
    sqlite_engine: Engine,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DATABASE_URL_VARIABLE, str(sqlite_engine.url))
    reference = "mod_local.notes.module:MODULE"

    assert main(["upgrade", "--module", reference, "--revision", "missing"]) == 1
    assert "missing" in capsys.readouterr().err
