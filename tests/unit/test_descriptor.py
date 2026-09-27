from __future__ import annotations

import sys
from importlib import invalidate_caches
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest
from sqlalchemy import Column, MetaData, String, Table

from stillhead import define_module, versions_dir
from stillhead.errors import (
    UnsupportedLayout,
)

if TYPE_CHECKING:
    from pathlib import Path


# --- The prefix ----------------------------------------------


def test_the_table_prefix_defaults_to_the_module_name(tmp_path: Path) -> None:
    module = define_module(name="notes", metadata=MetaData(), versions_path=tmp_path)

    assert module.table_prefix == "notes_"


def test_a_prefix_modules_version_table_carries_the_prefix(tmp_path: Path) -> None:
    module = define_module(name="notes", metadata=MetaData(), versions_path=tmp_path)

    assert module.version_table == "notes_alembic_version"


def test_derives_a_prefix_it_does_not_judge(tmp_path: Path) -> None:
    module = define_module(
        name="My Module", metadata=MetaData(), versions_path=tmp_path
    )

    assert module.table_prefix == "My Module_"


# --- Ownership -----------------


def test_owns_a_table_whose_name_starts_with_the_prefix(tmp_path: Path) -> None:
    module = define_module(name="notes", metadata=MetaData(), versions_path=tmp_path)

    assert module.owns_table("notes_note")
    assert not module.owns_table("sync_link")
    assert not module.owns_table(None)


def test_owns_only_its_tables_when_the_metadata_holds_others(tmp_path: Path) -> None:
    metadata = MetaData()
    other = Table("notes_note", metadata, Column("id", String(36)))
    own = Table("sync_link", metadata, Column("id", String(36)))

    module = define_module(name="sync", metadata=metadata, versions_path=tmp_path)

    assert module.owns_table(own.name)
    assert not module.owns_table(other.name)


# --- The versions directory ----------------------------------------


def test_versions_dir_resolves_packages_that_are_merely_importable() -> None:
    for package in ("mod_alpha", "mod_app.modules.beta", "mod_local.notes"):
        resolved = versions_dir(package)
        assert resolved.is_dir()
        assert resolved.name == "versions"


def test_versions_dir_refuses_a_zip_imported_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "zipped.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("mod_zipped/__init__.py", "")
        bundle.writestr("mod_zipped/versions/__init__.py", "")

    monkeypatch.setattr(sys, "path", [str(archive), *sys.path])
    invalidate_caches()

    with pytest.raises(UnsupportedLayout, match="mod_zipped"):
        versions_dir("mod_zipped")
