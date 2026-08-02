from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError
import yaml

from .errors import ManifestError
from .manifest_model import (
    FragmentConfig,
    NodeConfig,
    PipelineManifest,
    _expand_env,
)
from .profiles import get_profile


_NODE_RESERVED = {
    "use", "uses", "parameters", "inputs", "outputs", "synchronization",
    "execution", "failure", "health", "resources", "memory", "bindings",
    "placement",
}
_RESOURCE_RESERVED = {"use", "uses", "parameters", "bindings"}
_COMPACT_TOP_LEVEL = {
    "apiVersion", "kind", "metadata", "name", "description", "profile",
    "runtime", "sessions", "resources", "applications", "nodes", "blocks", "flow", "edges", "links",
    "streams", "publish", "fragments", "recording", "security", "placement",
}
_FRAGMENT_FIELDS = {
    "uses", "version", "description", "documentation", "tests", "parameters",
    "inputs", "outputs", "nodes", "blocks", "flow", "edges", "fragments",
    "hardware_requirements",
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def canonical_config_path(dotted: str, node_names: Iterable[str] | None = None) -> str:
    parts = [part for part in dotted.split(".") if part]
    known_nodes = set(node_names or ())
    if len(parts) >= 2 and parts[0] in known_nodes:
        parts.insert(0, "nodes")
    if len(parts) >= 3 and parts[0] == "nodes" and parts[2] not in {
        "uses", "parameters", "inputs", "outputs", "synchronization", "execution",
        "failure", "health", "resources", "memory", "bindings",
    }:
        parts.insert(2, "parameters")
    return ".".join(parts)


def _set_path(target: dict[str, Any], dotted: str, value: Any) -> None:
    dotted = canonical_config_path(dotted, dict(target.get("nodes") or {}).keys())
    parts = [part for part in dotted.split(".") if part]
    if not parts:
        raise ManifestError("Override path cannot be empty")
    cursor = target
    for part in parts[:-1]:
        next_value = cursor.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[part] = next_value
        cursor = next_value
    cursor[parts[-1]] = value


def _flatten_paths(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten_paths(item, path))
    elif isinstance(value, list):
        result[prefix] = value
    else:
        result[prefix] = value
    return result


def _parse_flow_item(item: Any) -> dict[str, Any]:
    if isinstance(item, str):
        if "->" not in item:
            raise ManifestError(f"Compact flow item must contain '->': {item!r}")
        source, target = (part.strip() for part in item.split("->", 1))
        return {"from": source, "to": target}
    if isinstance(item, dict):
        return deepcopy(item)
    raise ManifestError(f"Unsupported compact flow item: {item!r}")


def external_transport_bindings(
    manifest: PipelineManifest,
) -> tuple[dict[str, Any], ...]:
    """Return canonical external transport contracts, including 2.x links."""

    bindings = [
        {
            "from": edge.source,
            "to": edge.target,
            "uses": edge.transport.uses,
            "parameters": dict(edge.transport.parameters),
        }
        for edge in manifest.edges
        if edge.transport is not None
    ]
    bindings.extend(
        link.model_dump(by_alias=True, exclude_none=True, mode="json")
        for link in manifest.links
    )
    return tuple(bindings)


def _normalize_node(node_name: str, raw_node: Any, *, source: str) -> tuple[dict[str, Any], dict[str, str]]:
    if not isinstance(raw_node, dict):
        raise ManifestError(f"Node {node_name!r} from {source} must be a mapping")
    uses = raw_node.get("use", raw_node.get("uses"))
    if not uses:
        raise ManifestError(f"Node {node_name!r} from {source} requires 'use'")
    node: dict[str, Any] = {"uses": uses}
    direct_parameters = {key: deepcopy(value) for key, value in raw_node.items() if key not in _NODE_RESERVED}
    explicit_parameters = deepcopy(raw_node.get("parameters") or {})
    node["parameters"] = _deep_merge(direct_parameters, explicit_parameters)
    for key in _NODE_RESERVED - {"use", "uses", "parameters"}:
        if key in raw_node:
            node[key] = deepcopy(raw_node[key])
    sources = {
        f"nodes.{node_name}.{path}": source
        for path in _flatten_paths(node)
    }
    return node, sources


def _normalize_resource_entry(
    section: str,
    name: str,
    raw_value: Any,
    *,
    bindings: bool,
) -> dict[str, Any]:
    if not isinstance(raw_value, dict):
        raise ManifestError(
            f"{section}.{name} in compact pipeline must be a mapping"
        )
    uses = raw_value.get("uses", raw_value.get("use"))
    if not uses:
        raise ManifestError(
            f"{section}.{name} in compact pipeline requires 'uses'"
        )
    reserved = _RESOURCE_RESERVED if bindings else {
        "use",
        "uses",
        "parameters",
    }
    direct_parameters = {
        key: deepcopy(value)
        for key, value in raw_value.items()
        if key not in reserved
    }
    result: dict[str, Any] = {
        "uses": uses,
        "parameters": _deep_merge(
            direct_parameters,
            deepcopy(raw_value.get("parameters") or {}),
        ),
    }
    if bindings and "bindings" in raw_value:
        result["bindings"] = deepcopy(raw_value["bindings"])
    return result


def _block_path(value: Any, *, name: str, base_dir: Path) -> Path:
    if not isinstance(value, (str, Path)):
        raise ManifestError(f"Block {name!r} must be a YAML file path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    path = path.resolve()
    if not path.is_file():
        raise ManifestError(f"Block {name!r} does not exist: {path}")
    return path


def load_block(path: str | Path, *, name: str | None = None) -> NodeConfig:
    block_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(block_path.read_text(encoding="utf-8"))
        node, _ = _normalize_node(name or block_path.stem, raw, source=f"block:{block_path}")
        return NodeConfig.model_validate(_expand_env(node))
    except (OSError, yaml.YAMLError, ValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, ManifestError):
            raise
        raise ManifestError(f"Cannot load block {block_path}: {exc}") from exc


def load_fragment(path: str | Path, *, name: str | None = None) -> FragmentConfig:
    fragment_path = Path(path).expanduser().resolve()
    normalized = _load_fragment_value(
        name or fragment_path.stem,
        {"uses": str(fragment_path)},
        base_dir=fragment_path.parent,
    )
    try:
        return FragmentConfig.model_validate(_expand_env(normalized))
    except (ValidationError, TypeError, ValueError) as exc:
        raise ManifestError(f"Cannot load fragment {fragment_path}: {exc}") from exc


def _normalize_compact(
    raw: dict[str, Any], *, base_dir: Path
) -> tuple[dict[str, Any], dict[str, str], dict[str, Path]]:
    compact = "name" in raw or "flow" in raw or "publish" in raw or "blocks" in raw or any(
        isinstance(item, dict) and "use" in item for item in dict(raw.get("nodes") or {}).values()
    )
    sources: dict[str, str] = {}
    block_files: dict[str, Path] = {}
    if not compact:
        canonical = deepcopy(raw)
        for path in _flatten_paths(canonical):
            sources[path] = "pipeline.yaml"
        return canonical, sources, block_files

    unknown_fields = sorted(set(raw) - _COMPACT_TOP_LEVEL)
    if unknown_fields:
        raise ManifestError(
            "Unknown compact manifest fields: " + ", ".join(unknown_fields)
        )

    name = raw.get("name") or dict(raw.get("metadata") or {}).get("name")
    if not name:
        raise ManifestError("Compact manifest requires 'name'")
    canonical: dict[str, Any] = {
        "apiVersion": raw.get("apiVersion", "nodrix.dev/v1"),
        "kind": raw.get("kind", "Pipeline"),
        "metadata": {"name": name},
        "runtime": deepcopy(raw.get("runtime") or {}),
        "sessions": {},
        "resources": {},
        "applications": {},
        "nodes": {},
        "edges": [],
        "links": deepcopy(raw.get("links") or []),
        "streams": deepcopy(raw.get("streams") or {}),
        "fragments": deepcopy(raw.get("fragments") or {}),
        "recording": deepcopy(raw.get("recording") or {}),
        "security": deepcopy(raw.get("security") or {}),
        "placement": deepcopy(raw.get("placement") or {}),
    }
    if canonical["apiVersion"] == "nodrix.dev/v2":
        canonical["runtime"].setdefault("engine", "unified")
    description = raw.get("description") or dict(raw.get("metadata") or {}).get("description")
    if description:
        canonical["metadata"]["description"] = description
    profile = raw.get("profile")
    if profile:
        canonical["runtime"]["profile"] = profile

    for section, accepts_bindings in (
        ("sessions", False),
        ("resources", True),
        ("applications", True),
    ):
        raw_entries = raw.get(section) or {}
        if not isinstance(raw_entries, dict):
            raise ManifestError(
                f"Compact {section!r} must be a mapping"
            )
        canonical[section] = {
            str(entry_name): _normalize_resource_entry(
                section,
                str(entry_name),
                entry,
                bindings=accepts_bindings,
            )
            for entry_name, entry in raw_entries.items()
        }

    raw_blocks = raw.get("blocks") or {}
    if not isinstance(raw_blocks, dict):
        raise ManifestError("Compact 'blocks' must be a mapping of name: YAML path")
    for block_name, block_ref in raw_blocks.items():
        block_name = str(block_name)
        block_file = _block_path(block_ref, name=block_name, base_dir=base_dir)
        try:
            raw_block = yaml.safe_load(block_file.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ManifestError(f"Cannot read block {block_name!r} from {block_file}: {exc}") from exc
        node, node_sources = _normalize_node(
            block_name,
            raw_block,
            source=(
                "block:"
                + (
                    block_file.relative_to(base_dir).as_posix()
                    if block_file.is_relative_to(base_dir)
                    else block_file.as_posix()
                )
            ),
        )
        canonical["nodes"][block_name] = node
        sources.update(node_sources)
        block_files[block_name] = block_file

    for node_name, raw_node in dict(raw.get("nodes") or {}).items():
        if node_name in canonical["nodes"]:
            raise ManifestError(f"Node/block name is duplicated: {node_name!r}")
        node, node_sources = _normalize_node(str(node_name), raw_node, source="compact pipeline.yaml")
        canonical["nodes"][node_name] = node
        sources.update(node_sources)

    flow = raw.get("flow", raw.get("edges", []))
    canonical["edges"] = [_parse_flow_item(item) for item in flow]

    publish = raw.get("publish")
    if publish is not None:
        exports = list(canonical["streams"].get("exports") or [])
        if not isinstance(publish, dict):
            raise ManifestError("Compact 'publish' must be a mapping")
        for stream_name, value in publish.items():
            if isinstance(value, str):
                export = {"name": stream_name, "from": value}
            elif isinstance(value, dict):
                export = {"name": stream_name, **deepcopy(value)}
                if "source" in export and "from" not in export:
                    export["from"] = export.pop("source")
                access = export.get("access")
                if isinstance(access, str):
                    export["access"] = {"mode": access}
                    if access == "token":
                        export["access"]["token_env"] = "NODRIX_STREAM_TOKEN"
            else:
                raise ManifestError(f"Publish entry {stream_name!r} must be a string or mapping")
            exports.append(export)
        canonical["streams"]["exports"] = exports

    for path in _flatten_paths(canonical):
        sources.setdefault(path, "compact pipeline.yaml")
    return canonical, sources, block_files


def _apply_block_overrides(raw: dict[str, Any], overrides: list[str] | None) -> dict[str, Any]:
    if not overrides:
        return raw
    result = deepcopy(raw)
    blocks = result.get("blocks")
    if not isinstance(blocks, dict):
        raise ManifestError("--block requires a compact manifest with a 'blocks' mapping")
    for expression in overrides:
        if "=" not in expression:
            raise ManifestError(f"Block override must use name=path syntax: {expression!r}")
        name, path = (part.strip() for part in expression.split("=", 1))
        if not name or not path:
            raise ManifestError(f"Block override must use name=path syntax: {expression!r}")
        if name not in blocks:
            available = ", ".join(sorted(str(item) for item in blocks)) or "none"
            raise ManifestError(f"Unknown block {name!r}; available blocks: {available}")
        blocks[name] = path
    return result


def _apply_profile(
    canonical: dict[str, Any], sources: dict[str, str], profile_override: str | None
) -> tuple[dict[str, Any], dict[str, str]]:
    runtime = dict(canonical.get("runtime") or {})
    profile_name = profile_override or runtime.get("profile")
    if not profile_name:
        return canonical, sources
    try:
        profile = get_profile(str(profile_name))
    except ValueError as exc:
        raise ManifestError(str(exc)) from exc

    result = deepcopy(canonical)
    profile_runtime = deepcopy(profile.get("runtime") or {})
    profile_runtime["profile"] = profile_name
    result["runtime"] = _deep_merge(profile_runtime, runtime)

    node_defaults = dict(profile.get("node_defaults") or {})
    for node_name, node in dict(result.get("nodes") or {}).items():
        defaults = deepcopy(node_defaults.get(str(node.get("uses"))) or {})
        if defaults:
            result["nodes"][node_name] = _deep_merge(defaults, node)

    edge_defaults = deepcopy(profile.get("edge_defaults") or {})
    result["edges"] = [_deep_merge(edge_defaults, edge) for edge in list(result.get("edges") or [])]

    stream_defaults = deepcopy(profile.get("stream_defaults") or {})
    export_queue = stream_defaults.pop("queue", None)
    result["streams"] = _deep_merge(stream_defaults, dict(result.get("streams") or {}))
    if export_queue is not None:
        result["streams"]["exports"] = [
            _deep_merge({"queue": export_queue}, export)
            for export in list(result["streams"].get("exports") or [])
        ]

    for path in _flatten_paths(result):
        if path not in sources:
            sources[path] = f"profile:{profile_name}"
    return result, sources


def _load_fragment_value(
    name: str,
    value: Any,
    *,
    base_dir: Path,
    stack: tuple[Path, ...] = (),
) -> dict[str, Any]:
    if isinstance(value, (str, Path)):
        reference: dict[str, Any] = {"uses": str(value)}
    elif isinstance(value, dict):
        reference = deepcopy(value)
    else:
        raise ManifestError(f"Fragment {name!r} must be a mapping or YAML path")
    uses = reference.pop("uses", None)
    if uses is not None:
        path = Path(str(uses)).expanduser()
        if not path.is_absolute():
            path = base_dir / path
        path = path.resolve()
        if path in stack:
            chain = " -> ".join(str(item) for item in (*stack, path))
            raise ManifestError(f"Recursive fragment import: {chain}")
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ManifestError(f"Cannot load fragment {name!r} from {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ManifestError(f"Fragment file must contain a mapping: {path}")
        if "fragment" in loaded:
            loaded = loaded["fragment"]
        if not isinstance(loaded, dict):
            raise ManifestError(f"Fragment document is invalid: {path}")
        raw = _deep_merge(loaded, reference)
        fragment_base = path.parent
        next_stack = (*stack, path)
    else:
        raw = reference
        fragment_base = base_dir
        next_stack = stack
    unknown_fields = sorted(set(raw) - _FRAGMENT_FIELDS)
    if unknown_fields:
        raise ManifestError(
            f"Fragment {name!r} has unknown fields: "
            + ", ".join(unknown_fields)
        )
    raw_nodes = raw.get("nodes") or {}
    raw_blocks = raw.get("blocks") or {}
    if not isinstance(raw_nodes, dict) or not isinstance(raw_blocks, dict):
        raise ManifestError(f"Fragment {name!r} nodes/blocks must be mappings")
    if not raw_nodes and not raw_blocks:
        raise ManifestError(f"Fragment {name!r} requires nodes or blocks")
    nodes: dict[str, Any] = {}
    for node_name, node_value in raw_nodes.items():
        node, _ = _normalize_node(
            str(node_name),
            node_value,
            source=f"fragment:{name}",
        )
        nodes[str(node_name)] = node
    normalized_blocks: dict[str, str] = {}
    for block_name, block_value in raw_blocks.items():
        block_path = _block_path(
            block_value,
            name=str(block_name),
            base_dir=fragment_base,
        )
        try:
            raw_block = yaml.safe_load(block_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ManifestError(
                f"Cannot read fragment block {block_name!r}: {exc}"
            ) from exc
        node, _ = _normalize_node(
            str(block_name),
            raw_block,
            source=f"fragment-block:{block_path}",
        )
        nodes[str(block_name)] = node
        normalized_blocks[str(block_name)] = str(block_path)
    nested = {
        str(nested_name): _load_fragment_value(
            f"{name}.{nested_name}",
            nested_value,
            base_dir=fragment_base,
            stack=next_stack,
        )
        for nested_name, nested_value in dict(raw.get("fragments") or {}).items()
    }
    parameters = deepcopy(raw.get("parameters") or {})
    def set_fragment_parameter(
        target_nodes: dict[str, Any],
        target_fragments: dict[str, Any],
        parts: list[str],
        parameter_value: Any,
    ) -> bool:
        if len(parts) < 2:
            return False
        if parts[0] in target_fragments:
            child = target_fragments[parts[0]]
            return set_fragment_parameter(
                child["nodes"],
                child.get("fragments") or {},
                parts[1:],
                parameter_value,
            )
        if parts[0] not in target_nodes:
            return False
        cursor = target_nodes[parts[0]].setdefault("parameters", {})
        for part in parts[1:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = deepcopy(parameter_value)
        return True

    for dotted, parameter_value in parameters.items():
        if not set_fragment_parameter(
            nodes,
            nested,
            str(dotted).split("."),
            parameter_value,
        ):
            raise ManifestError(
                f"Fragment {name!r} parameter override references an unknown "
                f"node or nested fragment: {dotted!r}"
            )
    return {
        "version": str(raw.get("version", "1.0.0")),
        "description": raw.get("description"),
        "documentation": raw.get("documentation"),
        "tests": list(raw.get("tests") or []),
        "parameters": parameters,
        "inputs": deepcopy(raw.get("inputs") or {}),
        "outputs": deepcopy(raw.get("outputs") or {}),
        "nodes": nodes,
        "blocks": normalized_blocks,
        "edges": [_parse_flow_item(item) for item in raw.get("flow", raw.get("edges", []))],
        "fragments": nested,
        "hardware_requirements": list(raw.get("hardware_requirements") or []),
    }


def _expand_fragment(
    instance: str,
    fragment: dict[str, Any],
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, str],
    dict[str, str],
]:
    nodes = {
        f"{instance}__{name}": deepcopy(config)
        for name, config in dict(fragment["nodes"]).items()
    }
    nested_inputs: dict[str, dict[str, str]] = {}
    nested_outputs: dict[str, dict[str, str]] = {}
    edges: list[dict[str, Any]] = []
    for nested_name, nested in dict(fragment.get("fragments") or {}).items():
        child_instance = f"{instance}__{nested_name}"
        child_nodes, child_edges, child_inputs, child_outputs = _expand_fragment(
            child_instance,
            nested,
        )
        nodes.update(child_nodes)
        edges.extend(child_edges)
        nested_inputs[nested_name] = child_inputs
        nested_outputs[nested_name] = child_outputs

    def resolve(reference: str, *, source: bool) -> str:
        name, separator, port = str(reference).partition(".")
        if not separator:
            raise ManifestError(
                f"Fragment {instance!r} port reference must use node.port: {reference!r}"
            )
        if name in fragment["nodes"]:
            return f"{instance}__{name}.{port}"
        mappings = nested_outputs if source else nested_inputs
        if name in mappings and port in mappings[name]:
            return mappings[name][port]
        raise ManifestError(
            f"Fragment {instance!r} references unknown {'output' if source else 'input'}: {reference}"
        )

    for edge in fragment.get("edges") or []:
        resolved = deepcopy(edge)
        resolved["from"] = resolve(str(edge["from"]), source=True)
        resolved["to"] = resolve(str(edge["to"]), source=False)
        edges.append(resolved)
    inputs = {
        str(port): resolve(str(reference), source=False)
        for port, reference in dict(fragment.get("inputs") or {}).items()
    }
    outputs = {
        str(port): resolve(str(reference), source=True)
        for port, reference in dict(fragment.get("outputs") or {}).items()
    }
    return nodes, edges, inputs, outputs


def _normalize_and_expand_fragments(
    canonical: dict[str, Any],
    *,
    base_dir: Path,
) -> dict[str, Any]:
    result = deepcopy(canonical)
    raw_fragments = result.get("fragments") or {}
    if not isinstance(raw_fragments, dict):
        raise ManifestError("fragments must be a mapping")
    fragments = {
        str(name): _load_fragment_value(str(name), value, base_dir=base_dir)
        for name, value in raw_fragments.items()
    }
    result["fragments"] = fragments
    fragment_inputs: dict[str, dict[str, str]] = {}
    fragment_outputs: dict[str, dict[str, str]] = {}
    for name, fragment in fragments.items():
        nodes, edges, inputs, outputs = _expand_fragment(name, fragment)
        duplicated = sorted(set(result.get("nodes") or {}) & set(nodes))
        if duplicated:
            raise ManifestError(
                f"Fragment {name!r} expands to duplicate nodes: {', '.join(duplicated)}"
            )
        result.setdefault("nodes", {}).update(nodes)
        result.setdefault("edges", []).extend(edges)
        fragment_inputs[name] = inputs
        fragment_outputs[name] = outputs

    def resolve_outer(reference: str, *, source: bool) -> str:
        name, separator, port = str(reference).partition(".")
        if not separator:
            return reference
        mappings = fragment_outputs if source else fragment_inputs
        if name not in mappings:
            return reference
        if port not in mappings[name]:
            raise ManifestError(
                f"Fragment {name!r} has no public {'output' if source else 'input'} {port!r}"
            )
        return mappings[name][port]

    for edge in result.get("edges") or []:
        edge["from"] = resolve_outer(str(edge["from"]), source=True)
        edge["to"] = resolve_outer(str(edge["to"]), source=False)
    return result
