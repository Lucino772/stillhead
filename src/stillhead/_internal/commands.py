from __future__ import annotations

from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from sqlalchemy.engine import make_url

from stillhead._internal.schemas import check_schema
from stillhead.errors import DatabaseAheadOfBuild

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from stillhead._internal.module import ValidatedModule

# The shared Alembic environment and revision template, inside this package.
TEMPLATE_LOCATION = "stillhead:_template"


def upgrade(
    module: ValidatedModule,
    connection: Connection,
    revision: str = "head",
) -> None:
    """Upgrade the module to a revision. The default is head."""
    command.upgrade(_build_config(module, connection), revision)


def downgrade(
    module: ValidatedModule,
    connection: Connection,
    revision: str,
) -> None:
    """Downgrade the module to a revision."""
    command.downgrade(_build_config(module, connection), revision)


def emit_upgrade_sql(
    module: ValidatedModule,
    url: str,
    revision: str,
    schema: str | None = None,
) -> None:
    """Print the upgrade as SQL, and do not change the database.

    With a schema, the SQL starts by setting the search path.
    """
    if schema is not None:
        check_schema(schema, make_url(url).get_backend_name())
    command.upgrade(_build_config(module, url=url, schema=schema), revision, sql=True)


def create_revision(
    module: ValidatedModule,
    message: str,
    connection: Connection | None = None,
    autogenerate: bool = False,
) -> None:
    """Write a new revision file. Autogenerate needs a connection."""
    command.revision(
        _build_config(module, connection),
        message=message,
        autogenerate=autogenerate,
    )


def database_revision(module: ValidatedModule, connection: Connection) -> str | None:
    """Return the stamp of the module, or None when the database has none.

    Ends the transaction that the read starts. Leaves an open transaction open.
    """
    started = not connection.in_transaction()
    try:
        context = MigrationContext.configure(
            connection=connection,
            opts={
                "version_table": module.version_table,
                "version_table_schema": None,
            },
        )
        return context.get_current_revision()
    finally:
        if started and connection.in_transaction():
            connection.rollback()


def script_head(module: ValidatedModule) -> str | None:
    """Return the head of the module, or None when it has no revisions."""
    scripts = ScriptDirectory.from_config(_build_config(module))
    return scripts.get_current_head()


def pending_revisions(
    module: ValidatedModule,
    connection: Connection,
) -> tuple[str, ...]:
    """Return the pending revisions of the module, newest first.

    Raises an error when the stamp is not a revision of this build.
    """
    scripts = ScriptDirectory.from_config(_build_config(module))
    head = scripts.get_current_head()
    current = database_revision(module, connection)

    if head is None:
        # A stamp with no revisions on disk: the build lost its revisions.
        if current is not None:
            raise DatabaseAheadOfBuild(module.name, current, None, module.version_table)
        return ()

    if current is not None:
        # The revision map raises the specific error. The script directory
        # wraps it in a generic one.
        try:
            scripts.revision_map.get_revision(current)
        except ResolutionError as error:
            raise DatabaseAheadOfBuild(
                module.name, current, head, module.version_table
            ) from error

    walked = scripts.iterate_revisions(head, current)
    return tuple(script.revision for script in walked)


def _build_config(
    module: ValidatedModule,
    connection: Connection | None = None,
    url: str | None = None,
    schema: str | None = None,
) -> Config:
    """Build the Alembic configuration of one module.

    Without a connection, Alembic runs offline.
    """
    config = Config()
    config.set_main_option("script_location", TEMPLATE_LOCATION)
    config.set_main_option("version_locations", str(module.versions_path))
    config.set_main_option("path_separator", "os")
    # Option values are interpolated, so a literal percent sign is doubled.
    config.set_main_option("file_template", "%%(rev)s_%%(slug)s")

    if url is not None:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

    config.attributes["connection"] = connection
    config.attributes["module"] = module
    config.attributes["schema"] = schema
    return config
