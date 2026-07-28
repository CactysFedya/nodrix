from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import platform
import sys
import subprocess
from typing import Any

from .errors import RuntimeGraphError
from .manifest import PipelineManifest, dump_manifest_redacted, dump_source_manifest_redacted
from .packages import resolve_package_node
from .lockfile import build_lock
from . import __version__


@dataclass(frozen=True, slots=True)
class NativeNodeSpec:
    inputs: dict[str, str]
    outputs: dict[str, str]


NATIVE_BUILTINS: dict[str, NativeNodeSpec] = {
    "native.synthetic_source": NativeNodeSpec({}, {"output": "core.bytes"}),
    "native.identity": NativeNodeSpec({"input": "core.any"}, {"output": "core.any"}),
    "native.delay": NativeNodeSpec({"input": "core.any"}, {"output": "core.any"}),
    "native.counter_sink": NativeNodeSpec({"input": "core.any"}, {}),
}



def _find_project_root(path: Path) -> Path:
    resolved = path.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return resolved


def _hex(value: str) -> str:
    return value.encode("utf-8").hex()


class NativeToolchain:
    """Builds and locates the C++20 data plane shipped with Nodrix."""

    def __init__(self, project_dir: Path, build_dir: Path | None = None) -> None:
        self.project_dir = project_dir.resolve()
        self.source_dir = Path(__file__).with_name("native")
        self.build_dir = (build_dir or self.project_dir / ".nodrix" / "native-build").resolve()

    @property
    def runner(self) -> Path:
        name = "nodrix-native-runner.exe" if os.name == "nt" else "nodrix-native-runner"
        return self.build_dir / name

    def build(self, *, clean: bool = False, portable: bool = False, quiet: bool = False) -> Path:
        if clean and self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        generator: list[str] = []
        if shutil.which("ninja"):
            generator = ["-G", "Ninja"]
        configure = [
            "cmake",
            "-S",
            str(self.source_dir),
            "-B",
            str(self.build_dir),
            *generator,
            "-DCMAKE_BUILD_TYPE=Release",
            "-DNODRIX_NATIVE_LTO=ON",
            f"-DNODRIX_NATIVE_MARCH_NATIVE={'OFF' if portable else 'ON'}",
        ]
        io = {"stdout": subprocess.DEVNULL, "stderr": subprocess.PIPE, "text": True} if quiet else {}
        try:
            subprocess.run(configure, check=True, **io)
            jobs = str(max(1, os.cpu_count() or 1))
            subprocess.run(
                ["cmake", "--build", str(self.build_dir), "--parallel", jobs],
                check=True,
                **io,
            )
        except subprocess.CalledProcessError as exc:
            if quiet and exc.stderr:
                raise RuntimeGraphError(exc.stderr.strip()) from exc
            raise
        if not self.runner.exists():
            raise RuntimeGraphError(f"Native runner was not produced: {self.runner}")
        return self.runner

    def ensure_runner(self) -> Path:
        configured = os.environ.get("NODRIX_NATIVE_RUNNER")
        if configured:
            path = Path(configured).expanduser().resolve()
            if not path.exists():
                raise RuntimeGraphError(f"NODRIX_NATIVE_RUNNER does not exist: {path}")
            return path
        if self.runner.exists():
            return self.runner
        return self.build(quiet=True)

    def doctor(self) -> dict[str, Any]:
        return {
            "cmake": shutil.which("cmake"),
            "cxx": shutil.which(os.environ.get("CXX", "c++")),
            "ninja": shutil.which("ninja"),
            "source_dir": str(self.source_dir),
            "build_dir": str(self.build_dir),
            "runner": str(self.runner),
            "runner_exists": self.runner.exists(),
        }


class NativePipelineRuntime:
    """Python control plane for the native C++20 execution engine."""

    def __init__(
        self,
        manifest: PipelineManifest,
        manifest_path: Path,
        run_root: Path | None = None,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path.resolve()
        self.base_dir = self.manifest_path.parent
        self.run_root = (run_root or self.base_dir / ".nodrix" / "runs").resolve()
        self.specs: dict[str, NativeNodeSpec] = {}
        self.toolchain = NativeToolchain(_find_project_root(self.base_dir))

    def build(self) -> None:
        self.specs.clear()
        for name, config in self.manifest.nodes.items():
            resolved_uses = resolve_package_node(config.uses)
            if resolved_uses in NATIVE_BUILTINS:
                spec = NATIVE_BUILTINS[resolved_uses]
            elif resolved_uses.startswith("native:"):
                if not config.inputs and not config.outputs:
                    raise RuntimeGraphError(
                        f"Native plugin node {name!r} must declare inputs/outputs in the manifest"
                    )
                spec = NativeNodeSpec(dict(config.inputs), dict(config.outputs))
            else:
                raise RuntimeGraphError(
                    f"Native engine accepts only native.* or native:/library#type nodes; "
                    f"{name!r} uses {resolved_uses!r}"
                )
            self.specs[name] = spec

        connected_inputs: set[str] = set()
        for edge in self.manifest.edges:
            src_name, src_port = edge.source.split(".", 1)
            dst_name, dst_port = edge.target.split(".", 1)
            if src_name not in self.specs:
                raise RuntimeGraphError(f"Unknown source node: {src_name}")
            if dst_name not in self.specs:
                raise RuntimeGraphError(f"Unknown target node: {dst_name}")
            src = self.specs[src_name]
            dst = self.specs[dst_name]
            if src_port not in src.outputs:
                raise RuntimeGraphError(f"Node {src_name!r} has no output port {src_port!r}")
            if dst_port not in dst.inputs:
                raise RuntimeGraphError(f"Node {dst_name!r} has no input port {dst_port!r}")
            if edge.target in connected_inputs:
                raise RuntimeGraphError(f"Input {edge.target} already has a connection")
            connected_inputs.add(edge.target)
            source_type = src.outputs[src_port]
            target_type = dst.inputs[dst_port]
            if not self._types_compatible(source_type, target_type):
                raise RuntimeGraphError(
                    f"Type mismatch {edge.source} ({source_type}) -> "
                    f"{edge.target} ({target_type})"
                )

        for name, spec in self.specs.items():
            missing = [port for port in spec.inputs if f"{name}.{port}" not in connected_inputs]
            if missing:
                raise RuntimeGraphError(f"Node {name!r} has unconnected inputs: {missing}")
        if not any(not spec.inputs for spec in self.specs.values()):
            raise RuntimeGraphError("Native pipeline requires at least one source node")

    @staticmethod
    def _types_compatible(source: str, target: str) -> bool:
        return source == target or source == "core.any" or target == "core.any"

    def describe(self) -> dict[str, Any]:
        if not self.specs:
            self.build()
        return {
            "name": self.manifest.metadata.name,
            "mode": self.manifest.runtime.mode,
            "engine": "native",
            "nodes": {
                name: {
                    "class": config.uses,
                    "inputs": self.specs[name].inputs,
                    "outputs": self.specs[name].outputs,
                }
                for name, config in self.manifest.nodes.items()
            },
            "edges": [
                {
                    "from": edge.source,
                    "to": edge.target,
                    "type": self._edge_type(edge.source),
                    "queue": edge.queue.model_dump(),
                }
                for edge in self.manifest.edges
            ],
        }

    def _edge_type(self, source: str) -> str:
        node, port = source.split(".", 1)
        return self.specs[node].outputs[port]

    async def run(self) -> dict[str, Any]:
        if not self.specs:
            self.build()
        run_dir = self._create_run_dir()
        (run_dir / "logs").mkdir(exist_ok=True)
        (run_dir / "outputs").mkdir(exist_ok=True)
        dump_source_manifest_redacted(self.manifest_path, run_dir / "manifest.yaml")
        dump_manifest_redacted(self.manifest, run_dir / "resolved-manifest.yaml")
        (run_dir / "runtime.json").write_text(
            json.dumps({"runtime": "nodrix", "version": __version__, "engine": "native"}, indent=2), encoding="utf-8"
        )
        (run_dir / "environment.json").write_text(
            json.dumps({"python": platform.python_version(), "executable": sys.executable, "platform": platform.platform(), "machine": platform.machine()}, indent=2),
            encoding="utf-8",
        )
        try:
            (run_dir / "nodrix.lock").write_text(json.dumps(build_lock(self.manifest_path), indent=2, sort_keys=True), encoding="utf-8")
        except Exception as exc:
            (run_dir / "logs" / "lock-warning.log").write_text(str(exc), encoding="utf-8")
        plan = run_dir / "native-plan.vpp"
        plan.write_text(self._plan_text(run_dir), encoding="utf-8")
        runner = self.toolchain.ensure_runner()
        process = await asyncio.create_subprocess_exec(
            str(runner),
            "--plan",
            str(plan),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        (run_dir / "native.stdout.log").write_bytes(stdout)
        (run_dir / "native.stderr.log").write_bytes(stderr)
        report_path = run_dir / "native-run.json"
        if not report_path.exists():
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeGraphError(
                f"Native runner exited with {process.returncode} without a report: {detail}"
            )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["mode"] = self.manifest.runtime.mode
        report["native_runner"] = str(runner)
        report["stdout_log"] = str(run_dir / "native.stdout.log")
        report["stderr_log"] = str(run_dir / "native.stderr.log")
        report.setdefault("run_dir", str(run_dir))
        encoded = json.dumps(report, indent=2, ensure_ascii=False)
        (run_dir / "run.json").write_text(encoded, encoding="utf-8")
        (run_dir / "summary.json").write_text(encoded, encoding="utf-8")
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeGraphError(detail or f"Native runner exited with {process.returncode}")
        return report

    def _plan_text(self, run_dir: Path) -> str:
        lines = [
            "NODRIX_NATIVE_PLAN_V1",
            f"PIPELINE\t{_hex(self.manifest.metadata.name)}",
            f"RUN_DIR\t{_hex(str(run_dir))}",
        ]
        for name, config in self.manifest.nodes.items():
            uses = self._resolve_uses(resolve_package_node(config.uses))
            parameters = json.dumps(config.parameters, ensure_ascii=False, separators=(",", ":"))
            lines.append(f"NODE\t{_hex(name)}\t{_hex(uses)}\t{_hex(parameters)}")
        for edge in self.manifest.edges:
            src_name, src_port = edge.source.split(".", 1)
            dst_name, dst_port = edge.target.split(".", 1)
            lines.append(
                "\t".join(
                    [
                        "EDGE",
                        _hex(src_name),
                        _hex(src_port),
                        _hex(dst_name),
                        _hex(dst_port),
                        str(edge.queue.capacity),
                        edge.queue.policy,
                    ]
                )
            )
        lines.append("END")
        return "\n".join(lines) + "\n"

    def _resolve_uses(self, uses: str) -> str:
        if not uses.startswith("native:"):
            return uses
        body = uses.removeprefix("native:")
        if "#" not in body:
            raise RuntimeGraphError(
                f"Native plugin reference must use native:/path/library#node-type: {uses}"
            )
        library, node_type = body.rsplit("#", 1)
        path = Path(library).expanduser()
        if not path.is_absolute():
            path = (self.base_dir / path).resolve()
        if not path.exists():
            raise RuntimeGraphError(f"Native plugin library does not exist: {path}")
        return f"native:{path}#{node_type}"

    def _create_run_dir(self) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        safe_name = "".join(
            c if c.isalnum() or c in "-_" else "-" for c in self.manifest.metadata.name
        )
        run_dir = self.run_root / f"{timestamp}-{safe_name}"
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir
