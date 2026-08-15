#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
REQUIRED = (
    "index.md",
    "PRINCIPLES.md",
    "COMPATIBILITY.md",
    "adr/README.md",
    "planning/index.md",
    "planning/2.3.0b1-stabilization-plan.md",
    "DOCUMENTATION_SCOPE.md",
    "releases/index.md",
    "releases/2.3.0b1.md",
    "how-to/portable-deployment.md",
    "integrations/fast-livo2-semantic-mapping.md",
    "reference/stabilization-register.md",
    "ru/index.md",
    "ru/PRINCIPLES.md",
    "ru/COMPATIBILITY.md",
    "ru/adr/README.md",
    "ru/planning/index.md",
    "ru/planning/2.3.0b1-stabilization-plan.md",
    "ru/releases/index.md",
    "ru/releases/2.3.0b1.md",
    "ru/how-to/portable-deployment.md",
    "ru/integrations/fast-livo2-semantic-mapping.md",
    "ru/reference/stabilization-register.md",
)
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
TOCTREE = re.compile(r"^\s*([^:#\s][^#]*)\s*$")


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_required() -> None:
    for relative in REQUIRED:
        path = DOCS / relative
        if not path.is_file():
            fail(f"missing documentation page: docs/{relative}")


def check_release_alignment() -> None:
    for relative in REQUIRED:
        text = (DOCS / relative).read_text(encoding="utf-8")
        if "2.3.0a1" in text:
            fail(f"stale release 2.3.0a1 in docs/{relative}")
    for relative in ("index.md", "ru/index.md", "releases/index.md", "ru/releases/index.md"):
        if "2.3.0b1" not in (DOCS / relative).read_text(encoding="utf-8"):
            fail(f"current release is not visible in docs/{relative}")


def resolve_markdown_target(page: Path, raw_target: str) -> Path | None:
    target = raw_target.split("#", 1)[0].strip()
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    candidate = (page.parent / target).resolve()
    return candidate


def check_markdown_links() -> None:
    for relative in REQUIRED:
        page = DOCS / relative
        text = page.read_text(encoding="utf-8")
        for match in LINK.finditer(text):
            candidate = resolve_markdown_target(page, match.group(1))
            if candidate is not None and not candidate.exists():
                fail(
                    f"broken local link in {page.relative_to(ROOT)}: "
                    f"{match.group(1)}"
                )


def check_release_claims() -> None:
    release = (DOCS / "releases/2.3.0b1.md").read_text(encoding="utf-8")
    ru_release = (DOCS / "ru/releases/2.3.0b1.md").read_text(encoding="utf-8")
    for text, name in ((release, "EN release notes"), (ru_release, "RU release notes")):
        lowered = text.lower()
        if "experimental" not in lowered and "эксперимент" not in lowered:
            fail(f"{name} must state semantic-mapping qualification limits")
        if "setup" not in lowered:
            fail(f"{name} must distinguish planned setup automation")


def main() -> None:
    check_required()
    check_release_alignment()
    check_markdown_links()
    check_release_claims()
    print("Documentation checks passed for 2.3.0b1.")


if __name__ == "__main__":
    main()
