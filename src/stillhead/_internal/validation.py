from __future__ import annotations

import re
from typing import TYPE_CHECKING

from stillhead._internal.module import ValidatedModule
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
    from collections.abc import Iterable

    from stillhead._internal.module import ModuleMigrations

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def validate_module(module: ModuleMigrations) -> ValidatedModule:
    """Check one module, and return it as a valid module."""
    # NOTE: The metadata has no schema
    if module.metadata.schema is not None:
        raise SchemaOnMetadata(module.name, module.metadata.schema)

    # NOTE: The versions directory exists
    if not module.versions_path.is_dir():
        raise MissingVersionsDirectory(module.versions_path)

    # NOTE: The prefix is a lowercase identifier
    if not _IDENTIFIER.match(module.table_prefix):
        raise MissingOwnershipMarker(
            module.name, module.table_prefix, _IDENTIFIER.pattern
        )

    # NOTE: The module owns its version table, and no model table has its name
    if (
        not _IDENTIFIER.match(module.version_table)
        or not module.owns_table(module.version_table)
        or module.version_table in module.metadata.tables
    ):
        raise InvalidVersionTable(
            module.name, module.version_table, module.table_prefix
        )

    namespace = f"table prefix {module.table_prefix!r}"
    for table in module.metadata.tables.values():
        # NOTE: No table has a schema
        if table.schema is not None:
            raise SchemaOnMetadata(module.name, table.schema)

        # NOTE: The module owns each table in its metadata
        if not module.owns_table(table.name):
            raise ForeignNamespaceLeak(module.name, namespace, table.fullname)

        # NOTE: Each foreign key points to a table in the metadata of the module
        for key in table.foreign_keys:
            target = key.column.table
            if target.metadata is not module.metadata:
                raise ForeignKeyLeavesModule(module.name, target.fullname)

    return ValidatedModule(module)


def validate_module_set(modules: Iterable[ModuleMigrations]) -> list[ValidatedModule]:
    """Check each module, then check the modules together.

    Returns the modules as valid modules, in the given order.
    """
    validated = [validate_module(module) for module in modules]

    # NOTE: No two modules share a name
    seen: set[str] = set()
    for module in validated:
        if module.name in seen:
            raise DuplicateModuleName(module.name)
        seen.add(module.name)

    # NOTE: No prefix is the start of another prefix
    ordered = sorted(validated, key=lambda module: module.name)
    for index, module in enumerate(ordered):
        for other in ordered[index + 1 :]:
            mine, theirs = module.table_prefix, other.table_prefix
            if mine.startswith(theirs) or theirs.startswith(mine):
                raise DuplicateNamespace(
                    f"table prefix {mine!r} / {theirs!r}", (module.name, other.name)
                )

    return validated
