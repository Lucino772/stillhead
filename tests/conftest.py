from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

# Import the fixtures after the path insert.
from mod_alpha.module import MODULE as ALPHA_DECLARED
from mod_app.modules.beta.module import MODULE as BETA_DECLARED
from mod_local.notes.module import MODULE as NOTES_DECLARED
from mod_local.sync.module import MODULE as SYNC_DECLARED

from stillhead import validate_module

if TYPE_CHECKING:
    from stillhead import ValidatedModule


# Validate once: the commands and the guards need valid modules.
ALPHA = validate_module(ALPHA_DECLARED)
BETA = validate_module(BETA_DECLARED)
NOTES = validate_module(NOTES_DECLARED)
SYNC = validate_module(SYNC_DECLARED)


@pytest.fixture(scope="session")
def alpha() -> ValidatedModule:
    """A module in its own package."""
    return ALPHA


@pytest.fixture(scope="session")
def beta() -> ValidatedModule:
    """A module inside an application package."""
    return BETA


@pytest.fixture(scope="session")
def notes() -> ValidatedModule:
    """A module with one table."""
    return NOTES


@pytest.fixture(scope="session")
def sync() -> ValidatedModule:
    """A module with a foreign key between two of its tables."""
    return SYNC
