from __future__ import annotations

from mod_local.sync.models import metadata
from stillhead import define_module, versions_dir

MODULE = define_module(
    name="sync",
    metadata=metadata,
    versions_path=versions_dir("mod_local.sync"),
)
