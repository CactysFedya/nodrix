from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
with (ROOT / "pyproject.toml").open("rb") as stream:
    release = str(tomllib.load(stream)["project"]["version"])

project = "Plyctl"
author = "Plyctl contributors"
copyright = "2026, Plyctl contributors"
version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]
myst_enable_extensions = ["colon_fence", "deflist", "fieldlist"]
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
root_doc = "index"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_title = f"Plyctl {release} documentation"
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 4,
    "sticky_navigation": True,
}

linkcheck_ignore = [
    r"https://plyctl\.dev/.*",
    r"https://docs\.plyctl\.dev/.*",
]
