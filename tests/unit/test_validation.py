from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Column, ForeignKey, MetaData, String, Table

from stillhead import (
    ModuleMigrations,
    define_module,
    validate_module,
    validate_module_set,
)
from stillhead.errors import (
    DuplicateModuleName,
    DuplicateNamespace,
    ForeignKeyLeavesModule,
    ForeignNamespaceLeak,
    InvalidVersionTable,
    MissingOwnershipMarker,
    MissingVersionsDirectory,
    SchemaOnMetadata,
)

if TYPE_CHECKING:
    from pathlib import Path


def _module(name: str, versions_path: Path) -> ModuleMigrations:
    return define_module(name=name, metadata=MetaData(), versions_path=versions_path)


# --- One module ---


def test_rejects_metadata_that_declares_a_schema(tmp_path: Path) -> None:
    module = define_module(
        name="identity", metadata=MetaData(schema="tenancy"), versions_path=tmp_path
    )

    with pytest.raises(SchemaOnMetadata, match="tenancy"):
        validate_module(module)


def test_rejects_a_table_that_has_a_schema(tmp_path: Path) -> None:
    metadata = MetaData()
    Table("notes_note", metadata, Column("id", String(36)), schema="public")
    module = define_module(name="notes", metadata=metadata, versions_path=tmp_path)

    with pytest.raises(SchemaOnMetadata, match="public"):
        validate_module(module)


def test_rejects_a_versions_path_that_does_not_exist(tmp_path: Path) -> None:
    module = define_module(
        name="identity", metadata=MetaData(), versions_path=tmp_path / "nowhere"
    )

    with pytest.raises(MissingVersionsDirectory):
        validate_module(module)


def test_rejects_a_versions_path_that_is_a_file(tmp_path: Path) -> None:
    not_a_directory = tmp_path / "versions"
    not_a_directory.write_text("")
    module = define_module(
        name="identity", metadata=MetaData(), versions_path=not_a_directory
    )

    with pytest.raises(MissingVersionsDirectory):
        validate_module(module)


def test_rejects_a_prefix_that_is_not_a_plain_identifier(tmp_path: Path) -> None:
    module = define_module(
        name="My Module", metadata=MetaData(), versions_path=tmp_path
    )

    with pytest.raises(MissingOwnershipMarker, match="My Module_"):
        validate_module(module)


@pytest.mark.parametrize("prefix", ["Notes_", "1notes_", "no-tes_"])
def test_rejects_an_explicit_prefix_that_is_unsafe(prefix: str, tmp_path: Path) -> None:
    module = define_module(
        name="notes",
        metadata=MetaData(),
        versions_path=tmp_path,
        table_prefix=prefix,
    )

    with pytest.raises(MissingOwnershipMarker):
        validate_module(module)


def test_rejects_an_empty_prefix(tmp_path: Path) -> None:
    """The factory cannot make an empty prefix, so this test makes the definition directly."""
    module = ModuleMigrations(
        name="notes",
        metadata=MetaData(),
        versions_path=tmp_path,
        table_prefix="",
        version_table="notes_alembic_version",
    )

    with pytest.raises(MissingOwnershipMarker):
        validate_module(module)


def test_define_module_cannot_produce_an_empty_prefix(tmp_path: Path) -> None:
    module = define_module(
        name="notes", metadata=MetaData(), versions_path=tmp_path, table_prefix=""
    )

    assert module.table_prefix == "notes_"


def test_rejects_a_foreign_table_in_the_metadata(tmp_path: Path) -> None:
    metadata = MetaData()
    Table("notes_note", metadata, Column("id", String(36), primary_key=True))
    Table("sync_link", metadata, Column("id", String(36), primary_key=True))
    module = define_module(name="notes", metadata=metadata, versions_path=tmp_path)

    with pytest.raises(ForeignNamespaceLeak, match="sync_link"):
        validate_module(module)


def test_rejects_a_table_carrying_no_prefix(tmp_path: Path) -> None:
    metadata = MetaData()
    Table("stray", metadata, Column("id", String(36), primary_key=True))
    module = define_module(name="notes", metadata=metadata, versions_path=tmp_path)

    with pytest.raises(ForeignNamespaceLeak, match="stray"):
        validate_module(module)


def test_rejects_a_foreign_key_to_a_table_outside_the_metadata(tmp_path: Path) -> None:
    other = MetaData()
    foreign = Table("notes_note", other, Column("id", String(36), primary_key=True))
    metadata = MetaData()
    Table(
        "audit_entry",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("note_id", String(36), ForeignKey(foreign.c.id)),
    )
    module = define_module(name="audit", metadata=metadata, versions_path=tmp_path)

    with pytest.raises(ForeignKeyLeavesModule, match="notes_note"):
        validate_module(module)


def test_rejects_a_foreign_key_to_an_owned_name_in_another_schema(
    tmp_path: Path,
) -> None:
    other = MetaData(schema="other_schema")
    foreign = Table("notes_parent", other, Column("id", String(36), primary_key=True))
    metadata = MetaData()
    Table(
        "notes_child",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("parent_id", String(36), ForeignKey(foreign.c.id)),
    )
    module = define_module(name="notes", metadata=metadata, versions_path=tmp_path)

    with pytest.raises(ForeignKeyLeavesModule, match="other_schema"):
        validate_module(module)


def test_the_version_table_is_the_prefix_and_the_suffix(tmp_path: Path) -> None:
    module = define_module(
        name="notes",
        metadata=MetaData(),
        versions_path=tmp_path,
        version_table_suffix="migrations",
    )

    assert validate_module(module).version_table == "notes_migrations"


def test_rejects_a_version_table_that_the_module_does_not_own(tmp_path: Path) -> None:
    module = ModuleMigrations(
        name="notes",
        metadata=MetaData(),
        versions_path=tmp_path,
        table_prefix="notes_",
        version_table="sync_alembic_version",
    )

    with pytest.raises(InvalidVersionTable, match="sync_alembic_version"):
        validate_module(module)


def test_rejects_a_version_table_with_the_name_of_a_model_table(
    tmp_path: Path,
) -> None:
    metadata = MetaData()
    Table("notes_note", metadata, Column("id", String(36), primary_key=True))
    module = define_module(
        name="notes",
        metadata=metadata,
        versions_path=tmp_path,
        version_table_suffix="note",
    )

    with pytest.raises(InvalidVersionTable, match="notes_note"):
        validate_module(module)


@pytest.mark.parametrize("suffix", ["Version", "version-table", "version table"])
def test_rejects_a_version_table_that_is_not_an_identifier(
    suffix: str, tmp_path: Path
) -> None:
    module = define_module(
        name="notes",
        metadata=MetaData(),
        versions_path=tmp_path,
        version_table_suffix=suffix,
    )

    with pytest.raises(InvalidVersionTable):
        validate_module(module)


def test_allows_a_key_between_two_of_a_modules_own_tables(tmp_path: Path) -> None:
    metadata = MetaData()
    source = Table("sync_source", metadata, Column("id", String(36), primary_key=True))
    Table(
        "sync_link",
        metadata,
        Column("id", String(36), primary_key=True),
        Column("source_id", String(36), ForeignKey(source.c.id)),
    )

    validate_module(
        define_module(name="sync", metadata=metadata, versions_path=tmp_path)
    )


def test_returns_the_module_it_validated(tmp_path: Path) -> None:
    module = _module("notes", tmp_path)

    assert validate_module(module) is module


# --- A module set ---


def test_accepts_a_coherent_set(tmp_path: Path) -> None:
    validate_module_set([_module("notes", tmp_path), _module("sync", tmp_path)])


def test_rejects_a_duplicate_name(tmp_path: Path) -> None:
    with pytest.raises(DuplicateModuleName, match="notes"):
        validate_module_set(
            [
                _module("notes", tmp_path),
                _module("notes", tmp_path),
            ]
        )


def test_rejects_two_modules_claiming_one_table_prefix(tmp_path: Path) -> None:
    shared = define_module(
        name="two",
        metadata=MetaData(),
        versions_path=tmp_path,
        table_prefix="one_",
    )

    with pytest.raises(DuplicateNamespace, match="one_"):
        validate_module_set([_module("one", tmp_path), shared])


def test_rejects_a_shadowing_prefix(tmp_path: Path) -> None:
    with pytest.raises(DuplicateNamespace, match="notes_"):
        validate_module_set(
            [
                _module("notes", tmp_path),
                _module("notes_archive", tmp_path),
            ]
        )


def test_allows_prefixes_that_merely_share_leading_characters(tmp_path: Path) -> None:
    validate_module_set([_module("notes", tmp_path), _module("nodes", tmp_path)])


def test_a_set_with_no_overlap_needs_no_ordering(tmp_path: Path) -> None:
    notes, sync = _module("notes", tmp_path), _module("sync", tmp_path)

    assert validate_module_set([sync, notes]) == [sync, notes]
