from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Column, MetaData, String, Table, inspect, text

from stillhead import ValidatedModule, commands, validate_module
from stillhead.errors import ForeignNamespaceLeak, MigrationsDriftedFromModels
from stillhead.testing import assert_migrations_match_models, empty_namespaces
from tests.integration.conftest import enforcing_foreign_keys

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy import Engine

pytestmark = pytest.mark.integration


# --- Migrations match the models -----------------------------------------


def test_migrations_reproduce_the_models_for_schema_modules(
    alpha: ValidatedModule, beta: ValidatedModule, schema_engine: Engine
) -> None:
    with empty_namespaces([alpha, beta], schema_engine):
        assert_migrations_match_models(alpha, schema_engine)
        assert_migrations_match_models(beta, schema_engine)


def test_migrations_reproduce_the_models_for_prefix_modules(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    with empty_namespaces([notes, sync], prefix_engine):
        assert_migrations_match_models(notes, prefix_engine)
        assert_migrations_match_models(sync, prefix_engine)


def test_a_migration_that_drifted_from_its_models_fails(
    alpha: ValidatedModule, schema_engine: Engine
) -> None:
    with empty_namespaces([alpha], schema_engine):
        with schema_engine.connect() as connection:
            commands.upgrade(alpha, connection)
            connection.execute(text('ALTER TABLE alpha_thing DROP COLUMN "label"'))
            connection.commit()

        with pytest.raises(MigrationsDriftedFromModels, match="label"):
            assert_migrations_match_models(alpha, schema_engine)


# --- Empty namespaces -----------------------------------


def _tables_in(engine: Engine, schema: str | None = None) -> set[str]:
    with engine.connect() as connection:
        return set(inspect(connection).get_table_names(schema=schema))


def _populate(notes: ValidatedModule, sync: ValidatedModule, engine: Engine) -> None:
    """Apply both modules, and insert rows on both sides of a foreign key."""
    with engine.connect() as connection:
        commands.upgrade(notes, connection)
        commands.upgrade(sync, connection)
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


def test_module_namespace_leaves_nothing_behind(
    alpha: ValidatedModule, schema_engine: Engine
) -> None:
    with (
        empty_namespaces([alpha], schema_engine),
        schema_engine.connect() as connection,
    ):
        commands.upgrade(alpha, connection)

    assert "alpha_thing" not in _tables_in(schema_engine)
    assert "alpha_alembic_version" not in _tables_in(schema_engine)


def test_module_namespace_drops_only_what_the_module_owns(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)
        commands.upgrade(sync, connection)

    with empty_namespaces([sync], prefix_engine):
        assert "notes_note" in _tables_in(prefix_engine)
        assert "sync_link" not in _tables_in(prefix_engine)

    assert "notes_note" in _tables_in(prefix_engine)


def test_teardown_is_order_independent_when_nested(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    enforcing_foreign_keys(prefix_engine)

    with (
        empty_namespaces([sync], prefix_engine),
        empty_namespaces([notes], prefix_engine),
    ):
        _populate(notes, sync, prefix_engine)

    assert _tables_in(prefix_engine) == set()


def test_teardown_is_order_independent_when_nested_the_other_way(
    notes: ValidatedModule, sync: ValidatedModule, prefix_engine: Engine
) -> None:
    enforcing_foreign_keys(prefix_engine)

    with (
        empty_namespaces([notes], prefix_engine),
        empty_namespaces([sync], prefix_engine),
    ):
        _populate(notes, sync, prefix_engine)

    assert _tables_in(prefix_engine) == set()


@pytest.mark.parametrize("order", [("sync", "notes"), ("notes", "sync")])
def test_empty_namespaces_takes_whatever_order_it_is_given(
    order: tuple[str, str],
    notes: ValidatedModule,
    sync: ValidatedModule,
    prefix_engine: Engine,
) -> None:
    enforcing_foreign_keys(prefix_engine)
    by_name = {"notes": notes, "sync": sync}

    with empty_namespaces([by_name[name] for name in order], prefix_engine):
        _populate(notes, sync, prefix_engine)

    assert _tables_in(prefix_engine) == set()


# --- Autogenerate sees only the tables of the module ------------------------------------


def _with_writable_versions(module: ValidatedModule, tmp_path: Path) -> ValidatedModule:
    """Return the module with a copy of its versions directory, so a test can add revisions."""
    destination = tmp_path / "versions"
    destination.mkdir()
    for revision in module.versions_path.glob("*.py"):
        (destination / revision.name).write_bytes(revision.read_bytes())

    # A changed copy keeps the valid type, so validate it again.
    return validate_module(replace(module, versions_path=destination))


def _written_revision(module: ValidatedModule, slug: str) -> Path:
    written = list(module.versions_path.glob(f"*{slug}*.py"))
    assert len(written) == 1, f"expected one {slug} revision, got {written}"
    return written[0]


def test_autogenerate_never_mentions_another_modules_tables_in_a_schema(
    alpha: ValidatedModule,
    beta: ValidatedModule,
    schema_engine: Engine,
    tmp_path: Path,
) -> None:
    with empty_namespaces([alpha, beta], schema_engine):
        with schema_engine.connect() as connection:
            commands.upgrade(alpha, connection)
            commands.upgrade(beta, connection)

        scratch = _with_writable_versions(alpha, tmp_path)

        with schema_engine.connect() as connection:
            commands.create_revision(
                scratch, "guard check", connection=connection, autogenerate=True
            )

    generated = _written_revision(scratch, "guard_check").read_text()
    assert "beta_other" not in generated
    assert "drop_table" not in generated
    assert "create_table" not in generated


def test_autogenerate_never_mentions_another_modules_tables(
    notes: ValidatedModule,
    sync: ValidatedModule,
    prefix_engine: Engine,
    tmp_path: Path,
) -> None:
    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)
        commands.upgrade(sync, connection)

    scratch = _with_writable_versions(notes, tmp_path)

    with prefix_engine.connect() as connection:
        commands.create_revision(
            scratch, "guard check", connection=connection, autogenerate=True
        )

    generated = _written_revision(scratch, "guard_check").read_text()
    assert "sync_link" not in generated
    assert "sync_alembic_version" not in generated
    assert "drop_table" not in generated
    assert "create_table" not in generated


def test_a_module_changed_after_validation_is_refused(
    notes: ValidatedModule,
    prefix_engine: Engine,
    tmp_path: Path,
) -> None:
    """A changed copy keeps the valid type, so the migration validates the module again."""
    shared = MetaData()
    Table("notes_note", shared, Column("id", String(36), primary_key=True))
    Table("sync_source", shared, Column("id", String(36), primary_key=True))

    with prefix_engine.connect() as connection:
        commands.upgrade(notes, connection)

    mutated = replace(_with_writable_versions(notes, tmp_path), metadata=shared)

    with (
        prefix_engine.connect() as connection,
        pytest.raises(ForeignNamespaceLeak, match="sync_source"),
    ):
        commands.create_revision(
            mutated, "shared check", connection=connection, autogenerate=True
        )


def test_generated_revisions_pass_the_repo_lint_gate(
    alpha: ValidatedModule, schema_engine: Engine, tmp_path: Path
) -> None:
    with empty_namespaces([alpha], schema_engine):
        with schema_engine.connect() as connection:
            commands.upgrade(alpha, connection)

        scratch = _with_writable_versions(alpha, tmp_path)

        with schema_engine.connect() as connection:
            commands.create_revision(
                scratch, "lint check", connection=connection, autogenerate=True
            )
            commands.create_revision(scratch, "empty by hand", connection=connection)

    written = [
        _written_revision(scratch, "lint_check"),
        _written_revision(scratch, "empty_by_hand"),
    ]

    _run_ruff("check", written)
    _run_ruff("format", written, "--check")


def _run_ruff(subcommand: str, paths: list[Path], *flags: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", subcommand, "--no-cache", *flags]
        + [str(path) for path in paths],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, f"ruff {subcommand}:\n{result.stdout}{result.stderr}"
