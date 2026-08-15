"""Workspace-selectable human views for Nodrix runtime telemetry."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from .presentation import TOP_VIEW_SPECS, TopViewSpec
from .presentation import render_top_view as _render_top_view


_SECTION_NAMES = {
    "runtime",
    "health",
    "graph",
    "performance",
    "applications",
    "monitors",
    "queues",
    "attention",
    "debug",
}


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _builtin(view: str) -> TopViewSpec:
    selected = view.strip().lower()
    if selected == "compact":
        # Compatibility name, overview behavior.
        base = TOP_VIEW_SPECS["overview"]
        return TopViewSpec(**{**base.__dict__, "name": "compact"})
    try:
        return TOP_VIEW_SPECS[selected]
    except KeyError as exc:
        choices = "compact, overview, performance, operations, debug"
        raise ValueError(f"Unknown top view {view!r}; choose {choices}") from exc


def _from_sections(name: str, sections: list[str]) -> TopViewSpec:
    selected = {item.strip().lower() for item in sections if item.strip()}
    unknown = selected - _SECTION_NAMES
    if unknown:
        values = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown section(s) in view {name!r}: {values}")
    performance = "performance" in selected
    return TopViewSpec(
        name=name,
        show_runtime="runtime" in selected,
        show_health="health" in selected,
        show_graph="graph" in selected or performance,
        show_applications="applications" in selected,
        show_monitors="monitors" in selected,
        show_node_performance=performance,
        show_all_edges="queues" in selected,
        show_attention="attention" in selected,
        show_debug_details="debug" in selected,
    )


def resolve_top_view(view: str, project: Path | None = None) -> TopViewSpec:
    """Resolve a built-in view or a workspace ``nodrix.view/v1`` template.

    Custom view names are allowed when ``views/<name>.yaml`` declares
    ``sections``. A legacy/template file without ``sections`` inherits the
    built-in view with the same name, preserving existing workspaces.
    """

    path = (
        Path(project).expanduser().resolve() / "views" / f"{view}.yaml"
        if project is not None
        else None
    )
    if path is not None and path.is_file():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        config = _mapping(raw)
        schema = str(config.get("schema") or "")
        if schema and schema != "nodrix.view/v1":
            raise ValueError(
                f"Unsupported view schema {schema!r} in {path}; expected 'nodrix.view/v1'"
            )
        raw_sections = config.get("sections")
        if raw_sections is not None:
            if not isinstance(raw_sections, list) or not all(
                isinstance(item, str) for item in raw_sections
            ):
                raise ValueError(f"View sections must be a list of strings in {path}")
            return _from_sections(str(config.get("name") or view), raw_sections)

    return _builtin(view)


def render_top_view(
    data: dict[str, object],
    view: str = "compact",
    *,
    project: Path | None = None,
):
    return _render_top_view(data, resolve_top_view(view, project))


__all__ = ["TOP_VIEW_SPECS", "TopViewSpec", "resolve_top_view", "render_top_view"]
