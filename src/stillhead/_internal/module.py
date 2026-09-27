from __future__ import annotations

import importlib.resources
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NewType

from stillhead.errors import UnsupportedLayout

if TYPE_CHECKING:
    from sqlalchemy import MetaData


def versions_dir(package: str) -> Path:
    """Return the path of the versions directory inside a package.

    Works for an installed package, a source tree and a PyInstaller bundle.
    Raises an error when the directory has no path on disk, for example in a
    zip import.
    """
    path = importlib.resources.files(package) / "versions"
    if isinstance(path, Path):
        return path

    bundled_root = (
        Path(root)
        if isinstance((root := getattr(sys, "_MEIPASS", None)), str)
        else None
    )
    if (
        bundled_root is not None
        and (
            candidate := bundled_root.joinpath(*package.split("."), "versions")
        ).is_dir()
    ):
        return candidate

    raise UnsupportedLayout(package, frozen=bundled_root is not None)


@dataclass(frozen=True, slots=True, kw_only=True)
class ModuleMigrations:
    """The definition of one module. It checks nothing: validate it before use."""

    name: str
    metadata: MetaData
    versions_path: Path
    table_prefix: str
    version_table: str

    def owns_table(self, name: str | None) -> bool:
        """Return True when the module owns the table with this name."""
        return name is not None and name.startswith(self.table_prefix)


ValidatedModule = NewType("ValidatedModule", ModuleMigrations)
"""A module that passed validation.

It is the same object at run time, but a type checker treats it as a separate
type. A copy made with changes keeps this type: validate the copy again.
"""


def define_module(
    *,
    name: str,
    metadata: MetaData,
    versions_path: Path,
    table_prefix: str | None = None,
    version_table_suffix: str = "alembic_version",
) -> ModuleMigrations:
    """Create the definition of a module. It checks nothing.

    The prefix defaults to the module name and an underscore. The version table
    is the prefix followed by the suffix, so the module always owns it.
    """
    prefix = table_prefix or f"{name}_"
    return ModuleMigrations(
        name=name,
        metadata=metadata,
        versions_path=versions_path,
        table_prefix=prefix,
        version_table=f"{prefix}{version_table_suffix}",
    )
