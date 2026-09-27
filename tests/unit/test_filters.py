from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Column, MetaData, String, Table

from stillhead import ValidatedModule, define_module, validate_module
from stillhead.env import include_name_for, include_object_for

if TYPE_CHECKING:
    from pathlib import Path

metadata = MetaData()
owned = Table("notes_note", metadata, Column("id", String(36)))
foreign = Table("sync_link", metadata, Column("id", String(36)))
unprefixed = Table("legacy", metadata, Column("id", String(36)))


@pytest.fixture
def module(tmp_path: Path) -> ValidatedModule:
    return validate_module(
        define_module(name="notes", metadata=MetaData(), versions_path=tmp_path)
    )


def _table_parents(schema: str | None, name: str) -> dict[str, str | None]:
    qualified = f"{schema}.{name}" if schema else name
    return {
        "schema_name": schema,
        "table_name": name,
        "schema_qualified_table_name": qualified,
    }


# --- Filter for database tables -------------------------------------------


def test_keeps_the_namespace_the_search_path_resolves_to(
    module: ValidatedModule,
) -> None:
    assert include_name_for(module)(None, "schema", {})


def test_excludes_any_named_schema(module: ValidatedModule) -> None:
    assert not include_name_for(module)("orders", "schema", {})


def test_keeps_a_reflected_table_carrying_its_prefix(
    module: ValidatedModule,
) -> None:
    include = include_name_for(module)
    assert include("notes_note", "table", _table_parents(None, "notes_note"))


def test_excludes_another_modules_reflected_table(module: ValidatedModule) -> None:
    include = include_name_for(module)
    assert not include("sync_link", "table", _table_parents(None, "sync_link"))


def test_excludes_a_reflected_table_with_no_prefix(module: ValidatedModule) -> None:
    include = include_name_for(module)
    assert not include("legacy", "table", _table_parents(None, "legacy"))


def test_keeps_everything_that_is_neither_schema_nor_table(
    module: ValidatedModule,
) -> None:
    include = include_name_for(module)
    assert include("id", "column", _table_parents(None, "sync_link"))


# --- Filter for tables in the models and in the database -------------------


def test_keeps_a_table_in_its_own_metadata_carrying_its_prefix(
    module: ValidatedModule,
) -> None:
    include = include_object_for(module)
    assert include(owned, "notes_note", "table", False, None)


def test_excludes_another_modules_table_sharing_the_metadata(
    module: ValidatedModule,
) -> None:
    include = include_object_for(module)
    assert not include(foreign, "sync_link", "table", False, None)


def test_excludes_an_unprefixed_table_in_its_own_metadata(
    module: ValidatedModule,
) -> None:
    include = include_object_for(module)
    assert not include(unprefixed, "legacy", "table", False, None)


def test_keeps_non_tables(module: ValidatedModule) -> None:
    include = include_object_for(module)
    assert include(owned.c.id, "id", "column", False, None)
