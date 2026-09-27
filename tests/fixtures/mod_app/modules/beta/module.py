from __future__ import annotations

from mod_app.modules.beta.models import metadata
from stillhead import define_module, versions_dir

MODULE = define_module(
    name="beta",
    metadata=metadata,
    versions_path=versions_dir("mod_app.modules.beta"),
)
