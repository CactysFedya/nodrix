from __future__ import annotations

from pathlib import Path

_parent = Path(__file__).resolve().parents[1] / "conf.py"
exec(compile(_parent.read_text(encoding="utf-8"), str(_parent), "exec"), globals())

language = "ru"
html_title = "Документация Plyctl 2.3"
html_static_path = ["../_static"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
html_context = {
    **html_context,
    "conf_py_path": "/docs/ru/",
    "doc_language": "ru",
}
