from __future__ import annotations

from mod_alpha.models import metadata
from stillhead import define_module, versions_dir

MODULE = define_module(
    name="alpha",
    metadata=metadata,
    versions_path=versions_dir("mod_alpha"),
)
