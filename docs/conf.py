from __future__ import annotations

import os
from pathlib import Path
import tomllib


DOCS_DIR = Path(__file__).resolve().parent
ROOT = DOCS_DIR.parent
with (ROOT / "pyproject.toml").open("rb") as stream:
    release = str(tomllib.load(stream)["project"]["version"])

project = "Plyctl"
author = "Plyctl contributors"
copyright = "2026, Plyctl contributors"
version = ".".join(release.split(".")[:2])
language = os.environ.get("PLYCTL_DOCS_LANGUAGE", "en")

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]
myst_enable_extensions = ["colon_fence", "deflist", "fieldlist"]
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
root_doc = "index"

# Keep the public site focused on the current release. Historical release files
# stay in Git and CHANGELOG.md, but are not built or added to search results.
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "_landing",
    "_landing/**",
    "ru",
    "ru/**",
    "RELEASE_*.md",
    "*_RU.md",
    "releases",
    "releases/**",
]
# The repository contains additional expert reference pages that are reachable
# through links and search but intentionally absent from the primary sidebar.
suppress_warnings = ["toc.not_included"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_js_files = ["language-switcher.js"]
html_title = f"Plyctl {release} documentation"
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 4,
    "sticky_navigation": True,
    "titles_only": False,
}
html_context = {
    "docs_language": language,
    "display_github": True,
    "github_user": "CactysFedya",
    "github_repo": "nodrix",
    "github_version": "feature/2.2.0-modular-ros2",
    "conf_py_path": "/docs/",
}

linkcheck_ignore = [
    r"https://plyctl\.dev/.*",
    r"https://docs\.plyctl\.dev/.*",
]
