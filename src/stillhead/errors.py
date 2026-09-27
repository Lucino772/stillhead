from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


# --- Module definition -----------------------------------------------------


class InvalidSchemaName(ValueError):
    """A schema name that is not a lowercase identifier."""

    def __init__(self, schema: str, pattern: str) -> None:
        super().__init__(
            f"schema {schema!r} must match {pattern}, because it goes into "
            f"SQL without quotes."
        )


class SchemaOnMetadata(ValueError):
    """A module whose metadata, or one of its tables, has a schema."""

    def __init__(self, name: str, schema: str) -> None:
        super().__init__(
            f"module {name!r} gives the schema {schema!r} to its MetaData or to "
            f"a table. A module has no schema. Remove it, and give the schema "
            f"when you apply the migrations."
        )


class SchemaNotSupported(ValueError):
    """A schema on SQLite, which has no schemas."""

    def __init__(self, schema: str) -> None:
        super().__init__(
            f"SQLite has no schemas, so it cannot use the schema {schema!r}. "
            f"Use the default schema on SQLite."
        )


class MissingOwnershipMarker(ValueError):
    """A module whose prefix is not a lowercase identifier."""

    def __init__(self, name: str, prefix: str, pattern: str) -> None:
        super().__init__(
            f"module {name!r} has the prefix {prefix!r}, which does not match "
            f"{pattern}. Give a valid table_prefix, or change the module name."
        )


class MissingVersionsDirectory(ValueError):
    """A versions directory that does not exist."""

    def __init__(self, versions_path: Path) -> None:
        super().__init__(
            f"{str(versions_path)!r} is not a directory. Create the versions "
            f"directory, also when the module has no revisions."
        )


class UnsupportedLayout(RuntimeError):
    """A package whose versions directory has no path on disk."""

    def __init__(self, package: str, *, frozen: bool) -> None:
        cause = (
            f"{package} is frozen, and its versions directory is not in the "
            f"bundle. Add the directory to the datas of the .spec file."
            if frozen
            else f"{package} is imported from a zip file, so its versions "
            f"directory has no path on disk. Install the package unpacked."
        )
        super().__init__(f"{cause} Or give versions_path yourself.")


class InvalidVersionTable(ValueError):
    """A version table that the module does not own, or that is a model table."""

    def __init__(self, name: str, version_table: str, prefix: str) -> None:
        super().__init__(
            f"module {name!r} has the version table {version_table!r}. It must "
            f"start with the prefix {prefix!r}, be a lowercase identifier, and "
            f"not be the name of a table of the module. Change the suffix."
        )


class ForeignNamespaceLeak(ValueError):
    """A module whose metadata has a table that the module does not own."""

    def __init__(self, module_name: str, namespace: str, table_name: str) -> None:
        super().__init__(
            f"module {module_name!r} ({namespace}) has the table "
            f"{table_name!r} in its MetaData, but does not own it. Put only "
            f"the tables of the module in its MetaData."
        )


class ForeignKeyLeavesModule(ValueError):
    """A foreign key to a table that the module does not own."""

    def __init__(self, source: str, target: str) -> None:
        super().__init__(
            f"module {source!r} has a foreign key to {target!r}, which it does "
            f"not own. Remove the key, or make the two modules one module."
        )


# --- Module set ------------------------------------------------------------


class DuplicateModuleName(ValueError):
    """Two modules with the same name."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"two modules have the name {name!r}. Give each module a different name."
        )


class DuplicateNamespace(ValueError):
    """Two modules that can own the same tables."""

    def __init__(self, namespace: str, names: tuple[str, str]) -> None:
        super().__init__(
            f"modules {names[0]!r} and {names[1]!r} can own the same tables: "
            f"{namespace}. Change one of the prefixes."
        )


# --- Running migrations ----------------------------------------------------


class MissingConnection(RuntimeError):
    """An Alembic configuration without a SQLAlchemy connection."""

    def __init__(self, found: object) -> None:
        super().__init__(
            f"the Alembic configuration has a {type(found).__name__}, not a "
            f"SQLAlchemy Connection."
        )


class MissingOfflineUrl(RuntimeError):
    """Offline SQL without a database URL."""

    def __init__(self) -> None:
        super().__init__(
            "--sql needs a database URL to choose the SQL dialect. Set "
            "STILLHEAD_DATABASE_URL."
        )


class DatabaseAheadOfBuild(RuntimeError):
    """A stamp that is not a revision of this build."""

    def __init__(
        self, module: str, stamped: str, head: str | None, version_table: str
    ) -> None:
        self.module = module
        self.stamped = stamped
        self.head = head
        self.version_table = version_table
        current = (
            f"The head of this build is {head!r}."
            if head is not None
            else "This build has no revisions."
        )
        super().__init__(
            f"module {module!r} has the stamp {stamped!r}, which this build "
            f"does not have. {current} If a newer build migrated the database, "
            f"install that build or a newer one, and do not change the stamp. "
            f"If a branch changed a revision that the database already applied, "
            f"make a backup, then set the stamp in {version_table!r} to the last "
            f"revision that both branches share, or delete the database."
        )


class BrokenForeignKeys(RuntimeError):
    """A SQLite migration that leaves rows with a missing parent."""

    def __init__(self, module: str, broken: list[tuple[str, str]]) -> None:
        self.module = module
        self.broken = broken
        pairs = ", ".join(f"{table} -> {parent}" for table, parent in broken)
        super().__init__(
            f"module {module!r}: after the migration, rows point to missing "
            f"rows ({pairs}). The stamp stays at the previous revision. Change "
            f"the revision so that each foreign key stays valid."
        )


class OpenTransaction(RuntimeError):
    """A connection with an open transaction that stillhead did not start."""

    def __init__(self, *, at_end_of_block: bool) -> None:
        super().__init__(
            "the schema block ended with an open transaction. It is rolled "
            "back. Commit or roll back inside the block."
            if at_end_of_block
            else "the connection has an open transaction. Commit it or roll it "
            "back before you give the connection to stillhead."
        )


class AutocommitConnection(RuntimeError):
    """A connection in autocommit mode, which cannot roll back a revision."""

    def __init__(self) -> None:
        super().__init__(
            "the connection is in autocommit mode, so a failed revision cannot "
            "be rolled back. Give stillhead a connection without autocommit."
        )


class NoDriverConnection(RuntimeError):
    """A connection without a driver connection."""

    def __init__(self) -> None:
        super().__init__(
            "cannot set PRAGMA foreign_keys: the connection has no driver connection."
        )


class IrreversibleRevision(RuntimeError):
    """A revision that cannot be undone without data loss.

    Raise it in the downgrade function of that revision.
    """

    def __init__(self, revision: str) -> None:
        self.revision = revision
        super().__init__(
            f"revision {revision!r} cannot be undone. Downgrade to "
            f"{revision!r} itself, which keeps this revision, or restore a "
            f"backup made before the upgrade."
        )


# --- Command line ----------------------------------------------------------


class MissingDatabaseUrl(RuntimeError):
    """No database URL in the environment."""

    def __init__(self, variable: str) -> None:
        super().__init__(
            f"{variable} is not set. Example: "
            f"postgresql+psycopg://user:password@localhost:5432/app"
        )


class NoModulesNamed(ValueError):
    """A status command without a module."""

    def __init__(self) -> None:
        super().__init__(
            "status needs at least one module. Give --module "
            "package.module:ATTRIBUTE once for each module, for example "
            "--module myapp.notes.migrations:NOTES"
        )


class MalformedModuleReference(ValueError):
    """A module reference that is not package.module:ATTRIBUTE."""

    def __init__(self, reference: str) -> None:
        super().__init__(
            f"--module {reference!r} must be package.module:ATTRIBUTE, for "
            f"example myapp.notes.migrations:NOTES"
        )


class ModuleAttributeNotFound(ValueError):
    """A module reference whose attribute does not exist."""

    def __init__(self, reference: str) -> None:
        path, _, attribute = reference.partition(":")
        super().__init__(
            f"--module {reference!r}: {path} has no attribute {attribute!r}."
        )


class NotAModuleMigrations(TypeError):
    """A module reference that does not give a module definition."""

    def __init__(self, reference: str, loaded: object) -> None:
        super().__init__(
            f"--module {reference!r} gives a {type(loaded).__name__}, not a "
            f"ModuleMigrations."
        )


# --- Test guards -----------------------------------------------------------


class MigrationsDriftedFromModels(AssertionError):
    """A database, after all the revisions, that does not match the models."""

    def __init__(self, module_name: str, diff: object) -> None:
        super().__init__(
            f"module {module_name!r}: after all the revisions, the database "
            f"does not match the models. Differences:\n{diff}"
        )
