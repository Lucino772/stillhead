from __future__ import annotations

from alembic import context

from stillhead._internal.module import ModuleMigrations, ValidatedModule
from stillhead._internal.validation import validate_module
from stillhead.env import run_migrations


def _module() -> ValidatedModule:
    declared: object = context.config.attributes.get("module")
    if not isinstance(declared, ModuleMigrations):
        message = (
            "No module in the Alembic configuration. Run migrations with "
            "stillhead, not with the alembic command."
        )
        raise TypeError(message)

    # The valid-module type cannot be checked at run time, so validate again.
    return validate_module(declared)


run_migrations(_module())
