from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

project = "Plyctl"
author = "Plyctl contributors"
copyright = "2026, Plyctl contributors"
release = "2.3.0b1"
version = "2.3"

extensions = [
    "myst_parser",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
master_doc = "index"
language = os.environ.get("PLYCTL_DOC_LANGUAGE", "en")

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
    "substitution",
    "tasklist",
]
myst_heading_anchors = 3

exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "ru/**",
    "RELEASE_*.md",
    "*_RU.md",
    "archive/**",
]

html_theme = "sphinx_rtd_theme"
html_title = f"Plyctl {release} Documentation"
html_logo = None
html_favicon = None
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_js_files = ["language-switcher.js"]
html_show_sourcelink = True
html_show_sphinx = False
html_theme_options = {
    "navigation_depth": 4,
    "collapse_navigation": False,
    "sticky_navigation": True,
    "includehidden": True,
    "titles_only": False,
}
html_context = {
    "display_github": True,
    "github_user": "CactysFedya",
    "github_repo": "nodrix",
    "github_version": "release/2.3.0b1-stabilization",
    "conf_py_path": "/docs/",
    "doc_language": "en",
    "doc_version": "latest",
}

copybutton_prompt_text = r"^(\$ |>>> |\.\.\. )"
copybutton_prompt_is_regexp = True

nitpicky = False
suppress_warnings = ["myst.header", "toc.not_included"]
