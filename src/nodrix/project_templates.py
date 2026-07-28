from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Callable

import yaml


SKELETON_FILES: dict[str, str] = {
    "nodrix.toml": dedent(
        '''
        [project]
        name = "{project_name}"
        version = "0.1.0"
        default_pipeline = "pipeline.yaml"

        [runtime]
        engine = "unified"
        type_validation = "first"
        '''
    ).lstrip(),
    "requirements.txt": "nodrix==1.0.0\n",
    ".gitignore": ".nodrix/\noutputs/*\n!outputs/.gitkeep\n__pycache__/\n*.py[cod]\nbuild/\n*.so\n*.dylib\n.venv/\n",
    "pipeline.yaml": dedent(
        '''
        apiVersion: nodrix.dev/v1
        kind: Pipeline
        metadata:
          name: {project_name}
        runtime:
          mode: offline
          engine: unified
          type_validation: first
        # Add nodes and edges, or regenerate this directory with --template.
        nodes: {}
        edges: []
        streams:
          exports: []
        '''
    ).lstrip(),
    "nodes/__init__.py": '"""User Nodrix nodes."""\n',
    "configs/default.yaml": "runtime:\n  log_level: info\n",
    "types/README.md": "# Custom types\n\nAdd schemas here and run `nodrix type build`.\n",
    "models/.gitkeep": "",
    "data/.gitkeep": "",
    "outputs/.gitkeep": "",
    "tests/.gitkeep": "",
    "native/.gitkeep": "",
    "scripts/.gitkeep": "",
    "docs/README.md": "# Project documentation\n",
    "README.md": dedent(
        '''
        # {project_name}

        Empty Nodrix project skeleton. `pipeline.yaml` is intentionally not
        runnable until nodes are added.

        Create a runnable example instead:

        ```bash
        nodrix init {project_name} --template vision --force
        ```
        '''
    ).lstrip(),
}


NATIVE_EXAMPLE: dict[str, str] = {
    "native/README.md": dedent(
        '''
        # Native nodes

        Python nodes do not require a build. Compile this optional C++20 plugin
        only when a hot path needs native execution:

        ```bash
        cmake -S native -B native/build -DCMAKE_BUILD_TYPE=Release
        cmake --build native/build --parallel
        ```
        '''
    ).lstrip(),
    "native/passthrough.cpp": dedent(
        '''
        #include <span>
        #include <string_view>
        #include <vector>
        #include "nodrix/plugin.hpp"

        class Passthrough final : public nodrix::Node {
         public:
          const std::vector<nodrix::PortSpec>& input_ports() const noexcept override { return inputs_; }
          const std::vector<nodrix::PortSpec>& output_ports() const noexcept override { return outputs_; }
          void process(std::span<const nodrix::Message> inputs, nodrix::Emitter& emitter) override {
            if (!inputs.empty()) emitter.emit(0, inputs.front());
          }
         private:
          const std::vector<nodrix::PortSpec> inputs_{{"input", "core.any"}};
          const std::vector<nodrix::PortSpec> outputs_{{"output", "core.any"}};
        };

        NODRIX_DECLARE_PLUGIN(
          if (std::string_view(node_type ? node_type : "") == "example.passthrough") return new Passthrough();
          return nullptr;
        )
        '''
    ).lstrip(),
    "native/CMakeLists.txt": dedent(
        '''
        cmake_minimum_required(VERSION 3.20)
        project(nodrix_project_native LANGUAGES CXX)
        set(CMAKE_CXX_STANDARD 20)
        set(CMAKE_CXX_STANDARD_REQUIRED ON)
        find_package(Python3 REQUIRED COMPONENTS Interpreter)
        execute_process(
          COMMAND "${Python3_EXECUTABLE}" -c "from pathlib import Path; import nodrix; print(Path(nodrix.__file__).with_name('native'))"
          OUTPUT_VARIABLE NODRIX_NATIVE_DIR OUTPUT_STRIP_TRAILING_WHITESPACE)
        add_library(nodrix_passthrough SHARED passthrough.cpp)
        target_include_directories(nodrix_passthrough PRIVATE "${NODRIX_NATIVE_DIR}/include")
        target_compile_options(nodrix_passthrough PRIVATE
          $<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-O3;-DNDEBUG;-fvisibility=hidden>)
        '''
    ).lstrip(),
}


def _with_native(files: dict[str, str]) -> dict[str, str]:
    return {**NATIVE_EXAMPLE, **files}


def _core_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "apiVersion": "nodrix.dev/v1",
        "kind": "Pipeline",
        "metadata": {"name": project_name},
        "runtime": {"mode": "offline", "engine": "unified", "type_validation": "first"},
        "nodes": {
            "source": {"uses": "./nodes/source.py:CounterSource", "parameters": {"count": 100}},
            "transform": {"uses": "./nodes/transform.py:MultiplyNode", "parameters": {"factor": 2}},
            "sink": {"uses": "./nodes/sink.py:ConsoleSink"},
        },
        "edges": [
            {"from": "source.output", "to": "transform.input", "queue": {"capacity": 1024, "policy": "block"}},
            {"from": "transform.output", "to": "sink.input", "queue": {"capacity": 1024, "policy": "block"}},
        ],
        "streams": {"bind_host": "127.0.0.1", "exports": [
            {"name": f"/{project_name}/values", "from": "transform.output", "queue": {"capacity": 2, "policy": "latest"}},
        ]},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(pipeline, sort_keys=False),
        "nodes/source.py": dedent(
            '''
            from nodrix import Message, SourceNode

            class CounterSource(SourceNode):
                output_types = {"output": "core.object"}
                def produce(self):
                    for sequence in range(int(self.parameters.get("count", 100))):
                        yield {"output": Message(type="core.object", payload={"value": sequence}, sequence=sequence)}
            '''
        ).lstrip(),
        "nodes/transform.py": dedent(
            '''
            from nodrix import Node

            class MultiplyNode(Node):
                input_types = {"input": "core.object"}
                output_types = {"output": "core.object"}
                def open(self, context):
                    super().open(context)
                    self.factor = float(self.parameters.get("factor", 2))
                def process(self, inputs):
                    message = inputs["input"]
                    return {"output": message.with_updates(payload={"value": message.payload["value"] * self.factor})}
            '''
        ).lstrip(),
        "nodes/sink.py": dedent(
            """
            from nodrix import SinkNode

            class ConsoleSink(SinkNode):
                input_types = {"input": "core.object"}
                def process(self, inputs):
                    print(inputs["input"].payload)
            """
        ).lstrip(),
        "tests/test_nodes.py": dedent(
            '''
            from nodrix import Message
            from nodes.transform import MultiplyNode

            def test_multiply_node():
                node = MultiplyNode({"factor": 3})
                node.factor = 3
                result = node.process({"input": Message(type="core.object", payload={"value": 4})})
                assert result["output"].payload == {"value": 12}
            '''
        ).lstrip(),
        "scripts/run.sh": "#!/usr/bin/env bash\nset -euo pipefail\nnodrix run\n",
        "README.md": f"# {project_name}\n\n```bash\nnodrix validate\nnodrix run\n```\n",
    })


def _vision_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "apiVersion": "nodrix.dev/v1",
        "kind": "Pipeline",
        "metadata": {"name": project_name},
        "runtime": {"mode": "realtime", "engine": "unified", "type_validation": "first"},
        "nodes": {
            "camera": {"uses": "vision.video_source", "parameters": {"uri": 0, "realtime": True, "buffer_size": 1}},
            "detector": {"uses": "./nodes/detector.py:Detector"},
            "preview_encoder": {"uses": "vision.jpeg_encoder", "parameters": {"quality": 80}},
        },
        "edges": [
            {"from": "camera.frame", "to": "detector.frame", "queue": {"capacity": 1, "policy": "latest"}},
            {"from": "camera.frame", "to": "preview_encoder.frame", "queue": {"capacity": 1, "policy": "latest"}},
        ],
        "streams": {"bind_host": "127.0.0.1", "exports": [
            {"name": f"/{project_name}/preview", "from": "preview_encoder.frame", "queue": {"capacity": 1, "policy": "latest"}},
            {"name": f"/{project_name}/detections", "from": "detector.detections", "queue": {"capacity": 2, "policy": "latest"}},
        ]},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(pipeline, sort_keys=False),
        "requirements.txt": "nodrix[viewer]==1.0.0\n",
        "nodes/detector.py": dedent(
            '''
            import numpy as np
            from nodrix import Node
            from nodrix.vision import Detections

            class Detector(Node):
                input_types = {"frame": "vision.frame"}
                output_types = {"detections": "vision.detections"}
                def open(self, context):
                    super().open(context)
                    self.model = None  # Load ONNX/NCNN/TensorRT/OpenVINO here.
                def process(self, inputs):
                    source = inputs["frame"]
                    detections = Detections(
                        boxes=np.empty((0, 4), np.float32),
                        scores=np.empty((0,), np.float32),
                        class_ids=np.empty((0,), np.int32),
                    )
                    return {"detections": source.with_updates(type="vision.detections", payload=detections)}
            '''
        ).lstrip(),
        "README.md": f"# {project_name}\n\n```bash\nnodrix run\n# On a laptop:\nnodrix-viewer /{project_name}/preview\n```\n",
    })


def _media_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "apiVersion": "nodrix.dev/v1",
        "kind": "Pipeline",
        "metadata": {"name": project_name},
        "runtime": {"mode": "realtime", "engine": "unified", "type_validation": "first"},
        "nodes": {
            "source": {"uses": "media.ffmpeg_source", "parameters": {
                "uri": "lavfi:testsrc=size=640x360:rate=30", "width": 640, "height": 360, "fps": 30,
                "max_frames": 90, "low_latency": True, "realtime": True,
            }},
            "encoder": {"uses": "media.ffmpeg_encoder", "parameters": {
                "codec": "h264", "encoder": "libx264", "preset": "ultrafast", "tune": "zerolatency",
                "fps": 30, "keyint": 30,
            }},
            "writer": {"uses": "media.encoded_writer", "parameters": {
                "path": "media/output.h264", "codec": "h264",
            }},
        },
        "edges": [
            {"from": "source.frame", "to": "encoder.frame", "queue": {"capacity": 4, "policy": "block"}},
            {"from": "encoder.encoded", "to": "writer.frame", "queue": {"capacity": 8, "policy": "block"}},
        ],
        "streams": {"bind_host": "127.0.0.1", "exports": [
            {"name": f"/{project_name}/h264", "from": "encoder.encoded", "queue": {"capacity": 2, "policy": "latest"}},
        ]},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(pipeline, sort_keys=False),
        "requirements.txt": "nodrix[media,viewer]==1.0.0\n",
        "README.md": dedent(
            f"""
            # {project_name}

            Efficient Media/Data Plane example: one persistent H.264 encoder
            feeds both the raw recording and the Nodrix LAN stream. The encoded file is stored under the latest `.nodrix/runs/.../media/output.h264` artifact directory.

            ```bash
            nodrix media doctor
            nodrix run
            nodrix-viewer /{project_name}/h264
            ```
            """
        ).lstrip(),
    })


def _network_files(project_name: str) -> dict[str, str]:
    publisher = {
        "apiVersion": "nodrix.dev/v1", "kind": "Pipeline", "metadata": {"name": f"{project_name}-publisher"},
        "runtime": {"mode": "realtime", "engine": "unified"},
        "nodes": {"source": {"uses": "core.synthetic_source", "parameters": {"count": 1000000, "interval_ms": 100}}},
        "edges": [],
        "streams": {"bind_host": "0.0.0.0", "exports": [{
            "name": f"/{project_name}/events",
            "from": "source.output",
            "queue": {"capacity": 2, "policy": "latest"},
            "access": {"mode": "token", "token_env": "NODRIX_STREAM_TOKEN"},
        }]},
    }
    subscriber = {
        "apiVersion": "nodrix.dev/v1", "kind": "Pipeline", "metadata": {"name": f"{project_name}-subscriber"},
        "runtime": {"mode": "realtime", "engine": "unified"},
        "nodes": {
            "remote": {"uses": "core.stream_source", "parameters": {"name": f"/{project_name}/events", "max_messages": 5}},
            "sink": {"uses": "sink.console"},
        },
        "edges": [{"from": "remote.output", "to": "sink.input", "queue": {"capacity": 2, "policy": "latest"}}],
        "streams": {"exports": []},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(publisher, sort_keys=False),
        "subscriber.yaml": yaml.safe_dump(subscriber, sort_keys=False),
        "README.md": f"# {project_name}\n\nDevice A: `nodrix run`\n\nDevice B: `nodrix stream list && nodrix run subscriber.yaml`\n",
    })

def _data_plane_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "apiVersion": "nodrix.dev/v1", "kind": "Pipeline", "metadata": {"name": project_name},
        "runtime": {
            "mode": "offline", "engine": "unified", "type_validation": "first",
            "memory": {"shared_pool": {"block_size": 1048576, "capacity": 8, "threshold": 65536}},
        },
        "nodes": {
            "source": {"uses": "./nodes/shared_source.py:SharedSource", "parameters": {"count": 100, "bytes": 262144}},
            "worker": {
                "uses": "./nodes/checksum.py:Checksum", "execution": {"isolation": "process", "cpu_affinity": []},
                "failure": {"policy": "restart", "max_restarts": 3, "backoff_ms": 100},
            },
            "sink": {"uses": "sink.console"},
        },
        "edges": [
            {"from": "source.output", "to": "worker.input", "queue": {"capacity": 4, "policy": "block"}},
            {"from": "worker.output", "to": "sink.input", "queue": {"capacity": 4, "policy": "block"}},
        ],
        "streams": {"exports": []},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(pipeline, sort_keys=False),
        "nodes/shared_source.py": dedent(
            '''
            from nodrix import Message, SharedBufferPool, SourceNode

            class SharedSource(SourceNode):
                output_types = {"output": "core.bytes"}
                def open(self, context):
                    super().open(context)
                    self.count = int(self.parameters.get("count", 100))
                    self.size = int(self.parameters.get("bytes", 262144))
                    self.pool = SharedBufferPool(self.size, 8)
                def produce(self):
                    for sequence in range(self.count):
                        buffer = self.pool.acquire(self.size)
                        buffer.memoryview()[:] = bytes([sequence & 255]) * self.size
                        buffer.readonly = True
                        yield {"output": Message(type="core.bytes", payload=buffer, sequence=sequence)}
                def close(self):
                    self.pool.close()
            '''
        ).lstrip(),
        "nodes/checksum.py": dedent(
            '''
            import hashlib
            from nodrix import Node

            class Checksum(Node):
                input_types = {"input": "core.bytes"}
                output_types = {"output": "core.object"}
                def process(self, inputs):
                    source = inputs["input"]
                    digest = hashlib.blake2b(source.payload.memoryview(), digest_size=8).hexdigest()
                    return {"output": source.with_updates(type="core.object", payload={"checksum": digest})}
            '''
        ).lstrip(),
        "README.md": f"# {project_name}\n\n`nodrix inspect --live` demonstrates descriptor-only shared-memory input to an isolated worker.\n",
    })


def _device_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "apiVersion": "nodrix.dev/v1", "kind": "Pipeline", "metadata": {"name": project_name},
        "runtime": {
            "mode": "offline", "engine": "unified", "type_validation": "first",
            "memory": {
                "shared_pool": {"block_size": 1048576, "capacity": 4, "threshold": 65536},
                "process_output_pool": {"block_size": 1048576, "capacity": 4, "threshold": 65536},
            },
        },
        "nodes": {
            "source": {
                "uses": "./nodes/device_source.py:DeviceSource",
                "parameters": {"count": 32, "bytes": 262144},
                "execution": {"isolation": "process", "device": "cpu"},
            },
            "sink": {"uses": "./nodes/sink.py:MemorySink"},
        },
        "edges": [
            {
                "from": "source.output", "to": "sink.input",
                "queue": {"capacity": 4, "policy": "block"},
                "memory": {"domain": "shared", "allow_copy": False},
            },
        ],
        "streams": {"exports": []},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(pipeline, sort_keys=False),
        "nodes/device_source.py": dedent(
            '''
            from nodrix import Message, SourceNode

            class DeviceSource(SourceNode):
                output_types = {"output": "core.bytes"}
                output_memory = {"output": "shared"}
                def open(self, context):
                    super().open(context)
                    self.count = int(self.parameters.get("count", 32))
                    self.size = int(self.parameters.get("bytes", 262144))
                def produce(self):
                    for sequence in range(self.count):
                        buffer = self.allocate_output(self.size)
                        buffer.memoryview()[:] = bytes([sequence & 255]) * self.size
                        buffer.readonly = True
                        yield {"output": Message(type="core.bytes", payload=buffer, sequence=sequence)}
            '''
        ).lstrip(),
        "nodes/sink.py": dedent(
            '''
            from nodrix import SinkNode

            class MemorySink(SinkNode):
                input_types = {"input": "core.bytes"}
                input_memory = {"input": ["shared", "cpu"]}
                def open(self, context):
                    super().open(context)
                    self.count = 0
                def process(self, inputs):
                    payload = inputs["input"].payload
                    assert payload.memory_type.value == "shared"
                    self.count += 1
            '''
        ).lstrip(),
        "README.md": f"# {project_name}\n\nRun `nodrix device doctor`, `nodrix inspect --memory`, then `nodrix inspect --live`. The isolated source uses executor-owned shared output buffers with zero output copies.\n",
    })


def _benchmark_files(project_name: str) -> dict[str, str]:
    files = _core_files(project_name)
    manifest = yaml.safe_load(files["pipeline.yaml"])
    manifest["metadata"]["name"] = f"{project_name}-benchmark"
    manifest["nodes"]["source"]["parameters"]["count"] = 100000
    files["pipeline.yaml"] = yaml.safe_dump(manifest, sort_keys=False)
    files["README.md"] = f"# {project_name}\n\n`nodrix benchmark --warmup 2 --repeat 5`\n"
    return files



def _package_files(project_name: str) -> dict[str, str]:
    package_name = project_name.replace("_", "-")
    return {
        "nodrix.package.yaml": yaml.safe_dump({
            "format": "nodrix-package/1",
            "name": package_name,
            "version": "1.0.0",
            "nodrix": ">=1.0,<2.0",
            "nodes": {"passthrough": {"python": "python/passthrough.py:Passthrough"}},
        }, sort_keys=False),
        "python/passthrough.py": dedent(
            """
            from nodrix import Node

            class Passthrough(Node):
                input_types = {"input": "core.any"}
                output_types = {"output": "core.any"}
                def process(self, inputs):
                    return {"output": inputs["input"]}
            """
        ).lstrip(),
        "tests/test_package.py": dedent(
            """
            from python.passthrough import Passthrough
            from nodrix import Message

            def test_passthrough():
                node = Passthrough()
                message = Message("core.object", {"ok": True})
                assert node.process({"input": message})["output"] is message
            """
        ).lstrip(),
        "README.md": f"# {package_name}\n\nBuild and install:\n\n```bash\nnodrix package build .\nnodrix package install dist/{package_name}-1.0.0.ndpkg\n```\n",
    }

TEMPLATES: dict[str, Callable[[str], dict[str, str]]] = {
    "core": _core_files,
    "vision": _vision_files,
    "media": _media_files,
    "network": _network_files,
    "data-plane": _data_plane_files,
    "device": _device_files,
    "benchmark": _benchmark_files,
    "package": _package_files,
}


def create_project(directory: Path, template: str | None = None, *, force: bool = False) -> list[Path]:
    if template is not None and template not in TEMPLATES:
        raise ValueError(f"Unknown template {template!r}; choose: {', '.join(sorted(TEMPLATES))}")
    directory = directory.resolve()
    if directory.exists() and any(directory.iterdir()) and not force:
        raise FileExistsError(f"Directory is not empty: {directory}; use --force")
    directory.mkdir(parents=True, exist_ok=True)
    project_name = directory.name.replace(" ", "-").lower()
    files = {path: content.replace("{project_name}", project_name) for path, content in SKELETON_FILES.items()}
    if template is not None:
        files.update(TEMPLATES[template](project_name))
    created: list[Path] = []
    for relative, content in files.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if relative.endswith(".sh"):
            path.chmod(0o755)
        created.append(path)
    return created
