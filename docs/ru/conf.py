from __future__ import annotations

from pathlib import Path
import runpy


# Reuse the primary configuration so themes and extensions cannot drift.
_base = runpy.run_path(str(Path(__file__).resolve().parents[1] / "conf.py"))
globals().update(_base)

language = "ru"
html_title = f"Документация Plyctl {release}"
html_static_path = ["../_static"]
html_context = {
    **html_context,
    "docs_language": "ru",
    "conf_py_path": "/docs/ru/",
}
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
suppress_warnings = []
