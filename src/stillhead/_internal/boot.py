from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine

from stillhead._internal.commands import pending_revisions, upgrade
from stillhead._internal.schemas import use_schema
from stillhead._internal.validation import validate_module_set

if TYPE_CHECKING:
    from collections.abc import Iterable

    from stillhead._internal.module import ModuleMigrations


def apply_pending(
    modules: Iterable[ModuleMigrations],
    target: Engine | str,
    *,
    schema: str | None = None,
) -> None:
    """Apply the pending revisions of each module, up to head.

    Validates the modules first, then applies them in name order. Does nothing
    when no revision is pending. Accepts an engine or a URL, and disposes of
    the engine that it makes from a URL.

    Does not lock the database: only one process can apply migrations at a
    time. Raises an error when a stamp is not a revision of this build.
    """
    listed = validate_module_set(sorted(modules, key=lambda module: module.name))

    with ExitStack() as stack:
        engine = stack.enter_context(_with_engine(target))
        connection = stack.enter_context(engine.connect())
        if schema is not None:
            stack.enter_context(use_schema(connection, schema))

        for module in listed:
            if pending_revisions(module, connection):
                upgrade(module, connection)


@contextmanager
def _with_engine(target: Engine | str):
    if isinstance(target, Engine):
        yield target
    else:
        engine = create_engine(target)
        try:
            yield engine
        finally:
            engine.dispose()
