from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Annotated

from rich.table import Table
import typer
import yaml

from .cli_context import (
    _runtime,
    block_app,
    console,
    fragment_app,
    native_app,
    node_app,
    stream_app,
    type_app,
)
from .cv_types import TYPE_REGISTRY
from .discovery import discover_streams, resolve_stream
from .errors import NodrixError
from .manifest import load_block, load_fragment, load_manifest
from .native_runtime import NATIVE_BUILTINS, NativeToolchain
from .node_docs import parameter_schema
from .registry import BUILTINS, load_builtin_providers, load_node_class
from .streams import StreamClient
from .type_codegen import generate_type


@node_app.command("list")
def node_list(
    pipeline: Annotated[Path | None, typer.Option("--pipeline", "-p", help="Show only node types used by a pipeline")] = None,
) -> None:
    """List available node types, or only the types used by one pipeline."""
    load_builtin_providers()
    selected: dict[str, type] = dict(BUILTINS)
    title = f"Available node types ({len(selected)})"
    if pipeline is not None:
        manifest = load_manifest(pipeline)
        used = {config.uses for config in manifest.nodes.values()}
        selected = {name: cls for name, cls in BUILTINS.items() if name in used}
        title = f"Node types used by {manifest.metadata.name} ({len(selected)})"
    console.print(f"[bold]{title}[/bold]")
    groups: dict[str, list[tuple[str, type]]] = {}
    for node_id, cls in sorted(selected.items()):
        group = node_id.split(".", 1)[0].upper()
        groups.setdefault(group, []).append((node_id, cls))
    for group, items in groups.items():
        console.print(f"\n[cyan]{group}[/cyan]")
        for node_id, cls in items:
            optional = set(getattr(cls, "optional_inputs", ()))
            inputs = ", ".join(
                f"{name}{'?' if name in optional else ''}:{kind}"
                for name, kind in cls.input_types.items()
            ) or "source"
            outputs = ", ".join(f"{name}:{kind}" for name, kind in cls.output_types.items()) or "sink"
            console.print(f"  [bold]{node_id:<30}[/bold] {inputs} → {outputs}")


@node_app.command("create")
def node_create(
    name: Annotated[str, typer.Argument(help="Node name, for example custom-detector")],
    directory: Annotated[Path, typer.Option("--directory", "-d")] = Path("nodes"),
    inputs: Annotated[list[str] | None, typer.Option("--input", help="Port as name:type; repeatable")] = None,
    outputs: Annotated[list[str] | None, typer.Option("--output", help="Port as name:type; repeatable")] = None,
    language: Annotated[str, typer.Option("--language", "-l", help="python or cpp")] = "python",
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Generate a Python-first high-performance node or a native C++ node."""
    def parse_ports(values: list[str] | None, default: dict[str, str]) -> dict[str, str]:
        if not values:
            return default
        result: dict[str, str] = {}
        for value in values:
            if ":" not in value:
                raise typer.BadParameter(f"Port must use name:type syntax: {value!r}")
            port, type_name = value.split(":", 1)
            if not port or not type_name:
                raise typer.BadParameter(f"Invalid port: {value!r}")
            result[port] = type_name
        return result

    language = language.lower()
    if language not in {"cpp", "python"}:
        raise typer.BadParameter("--language must be cpp or python")
    input_ports = parse_ports(inputs, {"input": "core.any"})
    output_ports = parse_ports(outputs, {"output": "core.any"})
    class_name = "".join(
        part.capitalize() for part in name.replace("_", "-").split("-") if part
    ) + "Node"
    directory.mkdir(parents=True, exist_ok=True)

    if language == "python":
        path = directory / f"{name.replace('-', '_')}.py"
        if path.exists() and not force:
            raise typer.BadParameter(f"File exists: {path}; use --force")
        template_lines = [
            "from nodrix import Message, Node",
            "",
            "",
            f"class {class_name}(Node):",
            f"    input_types = {input_ports!r}",
            f"    output_types = {output_ports!r}",
            "",
            "    def open(self, context):",
            "        super().open(context)",
            "        # Load the model once here. ONNX/OpenCV/PyTorch native calls may release the GIL.",
            "",
            "    def process(self, inputs):",
            "        source = next(iter(inputs.values()))",
            "        output_port = next(iter(self.output_types))",
            "        output_type = self.output_types[output_port]",
            "        return {output_port: Message(type=output_type, payload=source.payload,",
            "            sequence=source.sequence, timestamp_ns=source.timestamp_ns,",
            "            trace_id=source.trace_id, metadata=dict(source.metadata),",
            "            created_ns=source.created_ns)}",
            "",
        ]
        path.write_text("\n".join(template_lines), encoding="utf-8")
        console.print(f"[green]Created[/green] {path}")
        console.print(f"Use in YAML: [bold]{path.as_posix()}:{class_name}[/bold]")
        return

    project = directory / name.replace("_", "-")
    if project.exists() and any(project.iterdir()) and not force:
        raise typer.BadParameter(f"Directory is not empty: {project}; use --force")
    project.mkdir(parents=True, exist_ok=True)
    cpp_inputs = ", ".join(
        f'{{sizeof(nodrix_port_v2), "{port}", "{type_name}", "any"}}'
        for port, type_name in input_ports.items()
    )
    cpp_outputs = ", ".join(
        f'{{sizeof(nodrix_port_v2), "{port}", "{type_name}", "any"}}'
        for port, type_name in output_ports.items()
    )
    node_type = name.replace("_", ".").replace("-", ".")
    source_lines = [
        "#include <array>",
        "#include <cstring>",
        "",
        '#include "nodrix/cpp_plugin.hpp"',
        "",
        f"class {class_name} final : public nodrix::c_api::Node {{",
        " public:",
        "  std::span<const nodrix_port_v2> input_ports() const noexcept override { return inputs_; }",
        "  std::span<const nodrix_port_v2> output_ports() const noexcept override { return outputs_; }",
        "",
        "  nodrix_status_v2 process(std::span<const nodrix_message_v2> inputs,",
        "                           const nodrix::c_api::Emitter& emitter) override {",
        "    // Replace with the detector/filter/tracker implementation.",
        "    // The host retains owned payloads emitted synchronously here.",
        "    if (!outputs_.empty() && !inputs.empty()) emitter.emit(0, inputs.front());",
        "    return NODRIX_STATUS_OK;",
        "  }",
        "",
        " private:",
        f"  const std::array<nodrix_port_v2, {len(input_ports)}> inputs_{{{{{cpp_inputs}}}}};",
        f"  const std::array<nodrix_port_v2, {len(output_ports)}> outputs_{{{{{cpp_outputs}}}}};",
        "};",
        "",
        'extern "C" NODRIX_C_EXPORT uint32_t nodrix_plugin_abi_version_v2() {',
        "  return NODRIX_C_ABI_VERSION;",
        "}",
        'extern "C" NODRIX_C_EXPORT uint64_t nodrix_plugin_features_v2() {',
        "  return NODRIX_C_FEATURE_TYPED_PORTS | NODRIX_C_FEATURE_MEMORY_DOMAINS |",
        "         NODRIX_C_FEATURE_ZERO_COPY_BUFFERS;",
        "}",
        'extern "C" NODRIX_C_EXPORT nodrix_status_v2 nodrix_plugin_create_v2(',
        "    uint32_t host_abi, const char* node_type, const char*,",
        "    nodrix_node_api_v2* output) {",
        "  if (host_abi != NODRIX_C_ABI_VERSION) return NODRIX_STATUS_ABI_MISMATCH;",
        f'  if (!node_type || std::strcmp(node_type, "{node_type}") != 0)',
        "    return NODRIX_STATUS_UNSUPPORTED;",
        f"  return nodrix::c_api::export_node(new {class_name}(), output);",
        "}",
        "",
    ]
    target = name.replace("-", "_")
    cmake_lines = [
        "cmake_minimum_required(VERSION 3.20)",
        f"project({target} LANGUAGES CXX)",
        "set(CMAKE_CXX_STANDARD 20)",
        "set(CMAKE_CXX_STANDARD_REQUIRED ON)",
        "find_package(Python3 REQUIRED COMPONENTS Interpreter)",
        "execute_process(",
        '  COMMAND "${Python3_EXECUTABLE}" -c "from pathlib import Path; import nodrix; print(Path(nodrix.__file__).with_name(\'native\'))"',
        "  OUTPUT_VARIABLE NODRIX_NATIVE_DIR OUTPUT_STRIP_TRAILING_WHITESPACE",
        ")",
        f"add_library({target} SHARED node.cpp)",
        f'target_include_directories({target} PRIVATE "${{NODRIX_NATIVE_DIR}}/include")',
        f"target_compile_options({target} PRIVATE $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-O3;-DNDEBUG;-fvisibility=hidden>)",
        f'set_target_properties({target} PROPERTIES OUTPUT_NAME "{target}")',
        "",
    ]
    (project / "node.cpp").write_text("\n".join(source_lines), encoding="utf-8")
    (project / "CMakeLists.txt").write_text("\n".join(cmake_lines), encoding="utf-8")
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    prefix = "" if sys.platform == "win32" else "lib"
    manifest = {
        "uses": f"native:./build/{prefix}{target}{suffix}#{node_type}",
        "inputs": input_ports,
        "outputs": output_ports,
        "parameters": {},
    }
    (project / "manifest-snippet.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )
    console.print(f"[green]Created C++ node[/green] {project}")
    console.print(
        f"Build: cmake -S {project} -B {project / 'build'} -DCMAKE_BUILD_TYPE=Release "
        f"&& cmake --build {project / 'build'}"
    )


@node_app.command("info")
def node_info(reference: str, base_dir: Path = Path.cwd()) -> None:
    """Show ports for a built-in or custom node."""
    try:
        cls = load_node_class(reference, base_dir=base_dir)
    except NodrixError as exc:
        console.print(f"[red]Cannot load node:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[bold]{reference}[/bold]\nClass: {cls.__module__}.{cls.__name__}")
    console.print("Inputs:", cls.input_types)
    console.print("Outputs:", cls.output_types)
    rows = parameter_schema(reference)
    if rows:
        table = Table(
            "Parameter",
            "Type",
            "Default",
            "Range / values",
            "Description",
        )
        for row in rows:
            table.add_row(
                str(row.get("name", "")),
                str(row.get("type", "")),
                str(row.get("default", "")),
                str(row.get("values", "")),
                str(row.get("description", "")),
            )
        console.print(table)


@block_app.command("list")
def block_list_command(
    project: Annotated[Path, typer.Option("--project", "-p", help="Project directory containing blocks/")] = Path.cwd(),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List reusable block YAML files under blocks/."""
    project = project.expanduser().resolve()
    root = project / "blocks"
    if not root.is_dir():
        if json_output:
            console.print_json("[]")
        else:
            console.print(f"[yellow]No blocks directory:[/yellow] {root}")
        return
    rows: list[dict[str, object]] = []
    for path in sorted((*root.rglob("*.yaml"), *root.rglob("*.yml"))):
        try:
            config = load_block(path)
            rows.append({
                "name": path.stem,
                "category": str(path.parent.relative_to(root)) if path.parent != root else "-",
                "path": str(path.relative_to(project)),
                "uses": config.uses,
                "parameters": config.parameters,
            })
        except Exception as exc:
            rows.append({
                "name": path.stem,
                "category": str(path.parent.relative_to(root)) if path.parent != root else "-",
                "path": str(path.relative_to(project)),
                "uses": f"ERROR: {exc}",
                "parameters": {},
            })
    if json_output:
        console.print_json(json.dumps(rows, default=str))
        return
    table = Table("Category", "Block", "Implementation", "Path")
    for row in rows:
        table.add_row(str(row["category"]), str(row["name"]), str(row["uses"]), str(row["path"]))
    console.print(table)
    if not rows:
        console.print("[yellow]No YAML blocks found.[/yellow]")


@block_app.command("inspect")
def block_inspect_command(
    block: Annotated[Path, typer.Argument(exists=True, readable=True, help="Block YAML file")],
    project: Annotated[Path, typer.Option("--project", "-p", help="Base directory for custom node paths")] = Path.cwd(),
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show one block implementation, ports, and configured parameters."""
    try:
        config = load_block(block)
        inputs = dict(config.inputs)
        outputs = dict(config.outputs)
        class_name = None
        if not inputs or not outputs:
            cls = load_node_class(config.uses, base_dir=project.expanduser().resolve())
            class_name = f"{cls.__module__}.{cls.__name__}"
            inputs = inputs or dict(cls.input_types)
            outputs = outputs or dict(cls.output_types)
    except Exception as exc:
        console.print(f"[red]Cannot inspect block:[/red] {exc}")
        raise typer.Exit(1)
    payload = {
        "path": str(block.expanduser().resolve()),
        "uses": config.uses,
        "class": class_name,
        "inputs": inputs,
        "outputs": outputs,
        "parameters": config.parameters,
        "execution": config.execution.model_dump(exclude_none=True),
        "health": config.health.model_dump(exclude_none=True),
    }
    if json_output:
        console.print_json(json.dumps(payload, default=str))
        return
    console.print(f"[bold]{block.stem}[/bold]")
    console.print(f"Implementation: {config.uses}")
    if class_name:
        console.print(f"Class: {class_name}")
    ports = Table("Direction", "Port", "Type")
    for name, message_type in inputs.items():
        ports.add_row("input", str(name), str(message_type))
    for name, message_type in outputs.items():
        ports.add_row("output", str(name), str(message_type))
    console.print(ports)
    params = Table("Parameter", "Value")
    for name, value in sorted(config.parameters.items()):
        params.add_row(str(name), yaml.safe_dump(value, sort_keys=False).strip())
    console.print(params)


@stream_app.command("list")
def stream_list(
    pipeline: Annotated[Path | None, typer.Option("--pipeline", "-p", help="Show exports declared by a local manifest")] = None,
    timeout: Annotated[float, typer.Option("--timeout", min=0.05, help="LAN discovery window in seconds")] = 1.2,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List named streams visible on the LAN; no agent or IP address is required."""
    if pipeline is not None:
        try:
            desc = _runtime(pipeline).describe()
        except Exception as exc:
            console.print(f"[red]Cannot inspect streams:[/red] {exc}")
            raise typer.Exit(1)
        streams = desc.get("streams", [])
        if json_output:
            console.print_json(json.dumps(streams))
            return
        table = Table("Name", "Source", "Type", "Queue")
        for item in streams:
            table.add_row(item["name"], item["source"], item["type"], f"{item['policy']}:{item['capacity']}")
        console.print(table)
        return

    streams = discover_streams(timeout=timeout)
    if json_output:
        console.print_json(json.dumps([{
            "name": item.name,
            "type": item.type,
            "host": item.host,
            "pipeline": item.pipeline,
            "endpoint": item.endpoint,
        } for item in streams]))
        return
    table = Table("Stream", "Type", "Host", "Pipeline", "Endpoint")
    for item in streams:
        table.add_row(item.name, item.type, item.host, item.pipeline, item.endpoint)
    console.print(table)
    if not streams:
        console.print("[yellow]No Nodrix streams discovered during the selected window.[/yellow]")


@fragment_app.command("validate")
def fragment_validate_command(
    fragment: Annotated[Path, typer.Argument(exists=True, readable=True)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a Fragment SDK manifest and show its public contracts."""
    try:
        config = load_fragment(fragment)
    except Exception as exc:
        console.print(f"[red]Invalid fragment:[/red] {exc}")
        raise typer.Exit(1)
    result = {
        "valid": True,
        "version": config.version,
        "inputs": config.inputs,
        "outputs": config.outputs,
        "nodes": sorted(config.nodes),
        "nested_fragments": sorted(config.fragments),
        "hardware_requirements": config.hardware_requirements,
    }
    if json_output:
        console.print_json(json.dumps(result))
        return
    console.print(f"[green]Valid fragment[/green] {fragment} v{config.version}")
    console.print(f"Inputs: {json.dumps(config.inputs)}")
    console.print(f"Outputs: {json.dumps(config.outputs)}")
    console.print(f"Nodes: {', '.join(sorted(config.nodes))}")


@fragment_app.command("init")
def fragment_init_command(
    name: Annotated[str, typer.Argument()],
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Create a minimal documented Fragment SDK package."""
    target = (output or Path(name)).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        console.print(f"[red]Directory is not empty:[/red] {target}")
        raise typer.Exit(1)
    target.mkdir(parents=True, exist_ok=True)
    fragment = {
        "version": "1.0.0",
        "description": f"Reusable {name} subgraph",
        "documentation": "README.md",
        "tests": ["tests/test_contract.py"],
        "inputs": {"input": "processor.input"},
        "outputs": {"output": "processor.output"},
        "nodes": {
            "processor": {
                "uses": "core.delay",
                "parameters": {"milliseconds": 0},
            }
        },
        "edges": [],
        "hardware_requirements": [],
    }
    (target / "fragment.yaml").write_text(
        yaml.safe_dump(fragment, sort_keys=False),
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {name}\n\nValidate with `nodrix fragment validate fragment.yaml`.\n",
        encoding="utf-8",
    )
    tests_dir = target / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_contract.py").write_text(
        "from nodrix import load_fragment\n\n"
        "def test_contract():\n"
        "    fragment = load_fragment('fragment.yaml')\n"
        "    assert fragment.inputs and fragment.outputs\n",
        encoding="utf-8",
    )
    console.print(f"[green]Created fragment SDK[/green] {target}")


@stream_app.command("info")
def stream_info(
    name: Annotated[str, typer.Argument(help="Named stream, for example /camera/front")],
    timeout: Annotated[float, typer.Option("--timeout", min=0.05)] = 1.2,
) -> None:
    """Resolve one named LAN stream and display its endpoint and type."""
    try:
        item = resolve_stream(name, timeout=timeout)
    except LookupError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    table = Table("Field", "Value")
    for key, value in (
        ("name", item.name), ("type", item.type), ("host", item.host),
        ("pipeline", item.pipeline), ("endpoint", item.endpoint), ("codec", item.codec),
    ):
        table.add_row(key, str(value))
    console.print(table)


@stream_app.command("echo")
def stream_echo(
    target: Annotated[str, typer.Argument(help="Stream name or nodrix:// or nodrix+tls:// URI")],
    count: Annotated[int, typer.Option("--count", "-n", min=1)] = 1,
    discovery_timeout: Annotated[float, typer.Option("--discovery-timeout", min=0.05)] = 3.0,
    token: Annotated[str | None, typer.Option("--token", help="Stream access token")] = None,
    ca_file: Annotated[Path | None, typer.Option("--ca", help="Trusted CA for TLS")] = None,
    certificate: Annotated[Path | None, typer.Option("--cert", help="Client certificate for mTLS")] = None,
    private_key: Annotated[Path | None, typer.Option("--key", help="Client private key for mTLS")] = None,
    server_hostname: Annotated[str | None, typer.Option("--server-name", help="Expected TLS server name")] = None,
    reconnect_attempts: Annotated[int, typer.Option("--reconnect-attempts", min=0, max=100)] = 0,
) -> None:
    """Subscribe directly to a stream and print message headers/payload summaries."""
    client = StreamClient(
        target,
        discovery_timeout=discovery_timeout,
        token=token,
        ca_file=str(ca_file) if ca_file else None,
        certificate=str(certificate) if certificate else None,
        private_key=str(private_key) if private_key else None,
        server_hostname=server_hostname,
        reconnect_attempts=reconnect_attempts,
    )
    try:
        client.connect()
        for _ in range(count):
            message = client.receive()
            payload = message.payload
            summary = {
                "stream": message.stream_id,
                "type": message.type,
                "sequence": message.sequence,
                "timestamp_ns": message.timestamp_ns,
                "payload_class": type(payload).__name__,
            }
            if hasattr(payload, "buffer") and hasattr(payload.buffer, "nbytes"):
                summary["payload_bytes"] = payload.buffer.nbytes
            elif hasattr(payload, "nbytes"):
                summary["payload_bytes"] = int(payload.nbytes)
            else:
                summary["payload"] = payload
            console.print_json(json.dumps(summary, default=str))
    except (OSError, EOFError, LookupError, ValueError) as exc:
        console.print(f"[red]Stream failed:[/red] {exc}")
        raise typer.Exit(1)
    finally:
        client.close()


@stream_app.command("view")
def stream_view(
    target: Annotated[str, typer.Argument(help="Stream name or nodrix:// URI")],
    fps: Annotated[float, typer.Option("--fps", min=0.0)] = 0.0,
    overlay: Annotated[bool, typer.Option("--overlay/--no-overlay")] = True,
    fullscreen: Annotated[bool, typer.Option("--fullscreen")] = False,
    scale: Annotated[float, typer.Option("--scale", min=0.05, max=8.0)] = 1.0,
) -> None:
    """Open a named frame stream in Nodrix Viewer."""
    from .viewer import ViewerError, run_viewer

    try:
        report = run_viewer(
            target,
            max_fps=fps,
            overlay=overlay,
            fullscreen=fullscreen,
            scale=scale,
        )
    except (ViewerError, OSError, LookupError, ValueError) as exc:
        console.print(f"[red]Viewer failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"Displayed {report['displayed']} frames at {report['display_fps']:.1f} FPS; "
        f"overwritten={report['overwritten']}"
    )


@type_app.command("list")
def type_list() -> None:
    """List standard and user-registered message types."""
    table = Table("Message type", "Version", "Compatible", "Payload", "Description")
    for name in TYPE_REGISTRY.names():
        definition = TYPE_REGISTRY.definition(name)
        payload = "any"
        if definition and definition.payload_type is not None:
            payload_type = definition.payload_type
            payload = (
                " | ".join(item.__name__ for item in payload_type)
                if isinstance(payload_type, tuple)
                else payload_type.__name__
            )
        table.add_row(
            name,
            str(definition.version if definition else 1),
            ",".join(str(item) for item in definition.compatible_versions) if definition else "1",
            payload,
            definition.description if definition else "",
        )
    console.print(table)


@type_app.command("info")
def type_info(name: str) -> None:
    """Show a registered message contract."""
    definition = TYPE_REGISTRY.definition(name)
    if definition is None:
        console.print(f"[yellow]Unregistered user type:[/yellow] {name}")
        return
    console.print(f"[bold]{name}[/bold]")
    console.print(f"Version: {definition.version}; compatible: {definition.compatible_versions}")
    console.print(f"Payload: {definition.payload_type or 'any'}")
    if definition.description:
        console.print(definition.description)


@type_app.command("build")
def type_build(
    schema: Annotated[Path, typer.Argument(exists=True, readable=True, help="YAML type schema")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Generated package directory")] = Path("generated_types"),
) -> None:
    """Generate matching Python/C++ fixed-layout types and a binary wire codec."""
    try:
        generated = generate_type(schema, output)
    except (OSError, ValueError, TypeError) as exc:
        console.print(f"[red]Type generation failed:[/red] {exc}")
        raise typer.Exit(1)
    table = Table("Artifact", "Path")
    for kind, path in generated.items():
        table.add_row(kind, str(path))
    console.print(table)


@native_app.command("build")
def native_build(
    directory: Annotated[Path, typer.Option("--directory", "-d", help="Project directory for build cache")] = Path.cwd(),
    clean: Annotated[bool, typer.Option("--clean", help="Remove the previous native build")] = False,
    portable: Annotated[bool, typer.Option("--portable", help="Do not tune binaries for the current CPU")] = False,
) -> None:
    """Build the C++20 runner with Release, LTO, and native CPU tuning."""
    toolchain = NativeToolchain(directory)
    try:
        runner = toolchain.build(clean=clean, portable=portable)
    except (subprocess.CalledProcessError, NodrixError, OSError) as exc:
        console.print(f"[red]Native build failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(f"[green]Built[/green] {runner}")


@native_app.command("doctor")
def native_doctor(
    directory: Annotated[Path, typer.Option("--directory", "-d")] = Path.cwd(),
) -> None:
    """Check the local compiler and native runner."""
    data = NativeToolchain(directory).doctor()
    table = Table("Component", "Value")
    for key, value in data.items():
        table.add_row(key, "not found" if value is None else str(value))
    console.print(table)


@native_app.command("nodes")
def native_nodes() -> None:
    """List built-in C++ nodes."""
    table = Table("Node", "Inputs", "Outputs")
    for name, spec in sorted(NATIVE_BUILTINS.items()):
        table.add_row(name, json.dumps(spec.inputs), json.dumps(spec.outputs))
    console.print(table)
