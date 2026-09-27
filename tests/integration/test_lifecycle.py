from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import QueuePool

from stillhead import apply_pending, commands, define_module, validate_module
from stillhead._internal.cli import DATABASE_URL_VARIABLE
from stillhead.errors import DatabaseAheadOfBuild
from stillhead.testing import empty_namespaces
from tests.integration.conftest import enforcing_foreign_keys

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from sqlalchemy import Engine

    from stillhead import ValidatedModule

pytestmark = pytest.mark.integration


@pytest.fixture
def clean(
    alpha: ValidatedModule, beta: ValidatedModule, schema_engine: Engine
) -> Iterator[None]:
    with empty_namespaces([alpha, beta], schema_engine):
        yield


def _tables_in(engine: Engine, schema: str | None = None) -> set[str]:
    """Return the table names in a schema, or in the default schema."""
    with engine.connect() as connection:
        return set(inspect(connection).get_table_names(schema=schema))


def _url_of(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _stamp(module: ValidatedModule, engine: Engine, revision: str) -> None:
    """Write a revision into the version table of a migrated module."""
    with engine.connect() as connection:
        connection.execute(
            text(f"UPDATE {module.version_table} SET version_num = :revision"),
            {"revision": revision},
        )
        connection.commit()


# --- Schema-owned modules, which only Postgres can express ------------------


def test_upgrade_creates_only_what_the_module_owns(
    alpha: ValidatedModule, schema_engine: Engine, clean: None
) -> None:
    with schema_engine.connect() as connection:
        commands.upgrade(alpha, connection)

    assert _tables_in(schema_engine) == {"alpha_thing", "alpha_alembic_version"}


def test_each_module_keeps_its_own_version_table(
    alpha: ValidatedModule,
    beta: ValidatedModule,
    schema_engine: Engine,
    clean: None,
) -> None:
    with schema_engine.connect() as connection:
        commands.upgrade(alpha, connection)
        commands.upgrade(beta, connection)

        assert commands.database_revision(alpha, connection) == "0001_alpha"
        assert commands.database_revision(beta, connection) == "0001_beta"

    assert _tables_in(schema_engine) == {
        "alpha_thing",
        "alpha_alembic_version",
        "beta_other",
        "beta_alembic_version",
    }


def test_the_full_lifecycle_runs_for_both_modules(
    alpha: ValidatedModule,
    beta: ValidatedModule,
    schema_engine: Engine,
    clean: None,
) -> None:
    with schema_engine.connect() as connection:
        for module in (alpha, beta):
            assert commands.script_head(module) == f"0001_{module.name}"
            assert commands.pending_revisions(module, connection) == (
                f"0001_{module.name}",
            )

        commands.upgrade(alpha, connection)
        commands.upgrade(beta, connection)

        for module in (alpha, beta):
            assert commands.pending_revisions(module, connection) == ()

        commands.downgrade(beta, connection, "base")
        commands.downgrade(alpha, connection, "base")

    assert _tables_in(schema_engine) == {
        "alpha_alembic_version",
        "beta_alembic_version",
    }


# --- The same, on both backends ---------------------------------------------


def test_two_modules_in_one_schema_have_separate_version_tables(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)
        commands.upgrade(sync, connection)

        assert commands.database_revision(notes, connection) == "0001_notes"
        assert commands.database_revision(sync, connection) == "0001_sync"

    assert _tables_in(prefix_engine) == {
        "notes_note",
        "notes_alembic_version",
        "sync_source",
        "sync_link",
        "sync_alembic_version",
    }


def test_migrating_creates_no_schema(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)
        commands.upgrade(sync, connection)

    with prefix_engine.connect() as connection:
        schemas = set(inspect(connection).get_schema_names())

    assert "notes" not in schemas
    assert "sync" not in schemas


def test_a_modules_own_foreign_key_is_enforced(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    enforcing_foreign_keys(prefix_engine)
    apply_pending([notes, sync], prefix_engine)

    with prefix_engine.connect() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                "INSERT INTO sync_link (id, source_id, remote_id) "
                "VALUES ('1', 'no-such-source', 'r')"
            )
        )
        connection.commit()


# --- Applying migrations at start-up ---------------------------------------


def test_apply_pending_brings_every_module_up(
    alpha: ValidatedModule,
    beta: ValidatedModule,
    schema_engine: Engine,
    clean: None,
) -> None:
    apply_pending([beta, alpha], schema_engine)

    assert _tables_in(schema_engine) == {
        "alpha_thing",
        "alpha_alembic_version",
        "beta_other",
        "beta_alembic_version",
    }

    with schema_engine.connect() as connection:
        assert commands.pending_revisions(alpha, connection) == ()
        assert commands.pending_revisions(beta, connection) == ()


def test_apply_pending_is_a_no_op_the_second_time_for_a_schema_module(
    alpha: ValidatedModule, schema_engine: Engine, clean: None
) -> None:
    apply_pending([alpha], schema_engine)
    apply_pending([alpha], schema_engine)

    with schema_engine.connect() as connection:
        assert commands.pending_revisions(alpha, connection) == ()


def test_apply_pending_brings_every_prefix_module_to_head(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    apply_pending([notes, sync], prefix_engine)

    with prefix_engine.connect() as connection:
        assert commands.pending_revisions(notes, connection) == ()
        assert commands.pending_revisions(sync, connection) == ()


def test_apply_pending_is_a_no_op_when_already_current(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    apply_pending([notes], prefix_engine)
    before = _tables_in(prefix_engine)

    apply_pending([notes], prefix_engine)

    assert _tables_in(prefix_engine) == before


def test_apply_pending_accepts_a_url_as_well_as_an_engine(
    notes: ValidatedModule, tmp_path: Path
) -> None:
    apply_pending([notes], f"sqlite+pysqlite:///{tmp_path / 'boot.db'}")

    assert (tmp_path / "boot.db").exists()


def test_apply_pending_closes_the_engine_it_made_from_a_url(
    notes: ValidatedModule, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: list[Engine] = []

    def remember(url: str) -> Engine:
        engine = create_engine(url)
        built.append(engine)
        return engine

    monkeypatch.setattr("stillhead._internal.boot.create_engine", remember)

    apply_pending([notes], f"sqlite+pysqlite:///{tmp_path / 'boot.db'}")

    assert len(built) == 1
    pool = built[0].pool
    assert isinstance(pool, QueuePool)
    assert pool.checkedin() == 0


def test_apply_pending_reads_no_environment_variable(
    notes: ValidatedModule,
    sqlite_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(DATABASE_URL_VARIABLE, raising=False)

    apply_pending([notes], sqlite_engine)

    assert "notes_note" in _tables_in(sqlite_engine)


# --- A stamp this build does not carry --------------------------------------

# Squashed away, deleted, and still stamped on somebody's database.
SQUASHED_AWAY = "0005_notes_squashed"


def test_a_stamp_this_build_does_not_ship_is_refused_by_name(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    apply_pending([notes], prefix_engine)
    _stamp(notes, prefix_engine, SQUASHED_AWAY)

    with (
        prefix_engine.connect() as connection,
        pytest.raises(DatabaseAheadOfBuild) as raised,
    ):
        commands.pending_revisions(notes, connection)

    message = str(raised.value)
    assert notes.name in message
    assert SQUASHED_AWAY in message
    assert "0001_notes" in message
    assert notes.version_table in message


def test_the_refused_stamp_travels_as_attributes_not_only_as_a_message(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    apply_pending([notes], prefix_engine)
    _stamp(notes, prefix_engine, SQUASHED_AWAY)

    with (
        prefix_engine.connect() as connection,
        pytest.raises(DatabaseAheadOfBuild) as raised,
    ):
        commands.pending_revisions(notes, connection)

    assert raised.value.module == notes.name
    assert raised.value.stamped == SQUASHED_AWAY
    assert raised.value.head == "0001_notes"
    assert raised.value.version_table == notes.version_table


def test_apply_pending_refuses_a_stamp_this_build_does_not_ship(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    apply_pending([notes], prefix_engine)
    _stamp(notes, prefix_engine, SQUASHED_AWAY)

    with pytest.raises(DatabaseAheadOfBuild):
        apply_pending([notes], prefix_engine)

    with prefix_engine.connect() as connection:
        assert commands.database_revision(notes, connection) == SQUASHED_AWAY


def test_a_stamp_with_no_revisions_on_disk_is_refused(
    notes: ValidatedModule, prefix_engine: Engine, tmp_path: Path
) -> None:
    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)

    versions = tmp_path / "versions"
    versions.mkdir()
    empty = validate_module(
        define_module(name="notes", metadata=notes.metadata, versions_path=versions)
    )

    with (
        prefix_engine.connect() as connection,
        pytest.raises(DatabaseAheadOfBuild, match="no revisions") as raised,
    ):
        commands.pending_revisions(empty, connection)

    assert raised.value.stamped == "0001_notes"
    assert raised.value.head is None


def test_a_dead_stamp_in_one_module_leaves_the_others_readable(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    apply_pending([notes, sync], prefix_engine)
    _stamp(sync, prefix_engine, SQUASHED_AWAY)

    with prefix_engine.connect() as connection:
        assert commands.pending_revisions(notes, connection) == ()

        with pytest.raises(DatabaseAheadOfBuild) as raised:
            commands.pending_revisions(sync, connection)

    assert raised.value.module == sync.name


# The one revision only the later build ships, so the earlier one is asked to
# read a stamp it has never heard of.
LATER_BUILD_REVISION = "0002_notes_later"

_LATER_REVISION = '''"""notes: a revision only a later build ships.

Revision ID: {revision}
Revises: {down_revision}
Create Date: 2026-09-08 00:00:00.000000
"""

from __future__ import annotations

revision: str = "{revision}"
down_revision: str | None = "{down_revision}"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    """Nothing. This revision only moves the stamp."""


def downgrade() -> None:
    """Nothing to undo."""
'''


def _later_build_of(module: ValidatedModule, versions_path: Path) -> ValidatedModule:
    """Return the module as a newer build has it: its revisions and one more."""
    head = commands.script_head(module)
    assert head is not None

    versions_path.mkdir()
    for revision in module.versions_path.glob("*.py"):
        shutil.copy(revision, versions_path / revision.name)
    (versions_path / f"{LATER_BUILD_REVISION}.py").write_text(
        _LATER_REVISION.format(revision=LATER_BUILD_REVISION, down_revision=head)
    )

    return validate_module(
        define_module(
            name=module.name, metadata=module.metadata, versions_path=versions_path
        )
    )


def test_a_database_a_later_build_migrated_is_refused_by_name(
    notes: ValidatedModule, prefix_engine: Engine, tmp_path: Path
) -> None:
    later = _later_build_of(notes, tmp_path / "later")
    apply_pending([later], prefix_engine)

    with (
        prefix_engine.connect() as connection,
        pytest.raises(DatabaseAheadOfBuild) as raised,
    ):
        commands.pending_revisions(notes, connection)

    assert raised.value.module == notes.name
    assert raised.value.stamped == LATER_BUILD_REVISION
    assert raised.value.version_table == notes.version_table


def test_a_stamp_of_this_build_is_accepted(
    notes: ValidatedModule, prefix_engine: Engine
) -> None:
    with prefix_engine.connect() as connection:
        assert commands.pending_revisions(notes, connection) == ("0001_notes",)

    apply_pending([notes], prefix_engine)

    with prefix_engine.connect() as connection:
        assert commands.pending_revisions(notes, connection) == ()


# --- Offline SQL -------------------------------------------------------------


def test_sql_mode_emits_the_ddl_without_touching_the_database(
    alpha: ValidatedModule,
    schema_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands.emit_upgrade_sql(alpha, _url_of(schema_engine), "head")

    emitted = capsys.readouterr().out
    assert "CREATE TABLE alpha_thing" in emitted


def test_sql_mode_never_emits_create_schema(
    notes: ValidatedModule,
    prefix_engine: Engine,
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands.emit_upgrade_sql(notes, _url_of(prefix_engine), "head")

    emitted = capsys.readouterr().out
    assert "CREATE SCHEMA" not in emitted
    assert "CREATE TABLE notes_note" in emitted
