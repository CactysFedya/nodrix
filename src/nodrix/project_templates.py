from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Callable

import yaml

from .branding import MANIFEST_API_V2
from .manifest_schema import write_manifest_schema


def _manifest_v2(document: dict) -> dict:
    result = dict(document)
    result["apiVersion"] = MANIFEST_API_V2
    runtime = dict(result.get("runtime") or {})
    runtime.setdefault("engine", "unified")
    result["runtime"] = runtime
    result.setdefault("fragments", {})
    result.setdefault("recording", {})
    result.setdefault("security", {})
    result.setdefault("placement", {})
    result.setdefault("streams", {})
    result.setdefault("edges", [])
    return result


SKELETON_FILES: dict[str, str] = {
    ".vscode/settings.json": dedent(
        '''
        {
          "yaml.schemas": {
            ".plyctl-schema.json": [
              "pipeline.yaml",
              "pipelines/*.yaml"
            ]
          }
        }
        '''
    ).lstrip(),
    "plyctl.toml": dedent(
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
    "requirements.txt": "plyctl==2.2.0a5\n",
    ".gitignore": ".nodrix/\n/outputs/*\n!/outputs/.gitkeep\n__pycache__/\n*.py[cod]\nbuild/\n*.so\n*.dylib\n.venv/\n",
    "pipeline.yaml": dedent(
        '''
        apiVersion: plyctl.dev/v2
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
        fragments: {}
        recording: {}
        security: {}
        placement: {}
        '''
    ).lstrip(),
    "nodes/__init__.py": '"""User Plyctl nodes."""\n',
    "types/README.md": "# Custom types\n\nAdd schemas here and run `plyctl type build`.\n",
    "models/.gitkeep": "",
    "data/.gitkeep": "",
    "outputs/.gitkeep": "",
    "tests/.gitkeep": "",
    "scripts/.gitkeep": "",
    "docs/README.md": "# Project documentation\n",
    "README.md": dedent(
        '''
        # {project_name}

        Empty Plyctl project skeleton. `pipeline.yaml` is intentionally not
        runnable until nodes are added.

        Create a runnable example instead:

        ```bash
        plyctl init {project_name} --template vision --force
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
        #include <array>
        #include <cstring>
        #include <string_view>
        #include "nodrix/cpp_plugin.hpp"

        class Passthrough final : public nodrix::c_api::Node {
         public:
          std::span<const nodrix_port_v2> input_ports() const noexcept override { return inputs_; }
          std::span<const nodrix_port_v2> output_ports() const noexcept override { return outputs_; }
          nodrix_status_v2 process(
              std::span<const nodrix_message_v2> inputs,
              const nodrix::c_api::Emitter& emitter) override {
            if (!inputs.empty()) emitter.emit(0, inputs.front());
            return NODRIX_STATUS_OK;
          }
         private:
          const std::array<nodrix_port_v2, 1> inputs_{{{sizeof(nodrix_port_v2), "input", "core.any", "any"}}};
          const std::array<nodrix_port_v2, 1> outputs_{{{sizeof(nodrix_port_v2), "output", "core.any", "any"}}};
        };

        extern "C" NODRIX_C_EXPORT uint32_t nodrix_plugin_abi_version_v2() {
          return NODRIX_C_ABI_VERSION;
        }
        extern "C" NODRIX_C_EXPORT uint64_t nodrix_plugin_features_v2() {
          return NODRIX_C_FEATURE_TYPED_PORTS | NODRIX_C_FEATURE_MEMORY_DOMAINS |
                 NODRIX_C_FEATURE_ZERO_COPY_BUFFERS;
        }
        extern "C" NODRIX_C_EXPORT nodrix_status_v2 nodrix_plugin_create_v2(
            uint32_t host_abi, const char* node_type, const char*,
            nodrix_node_api_v2* output) {
          if (host_abi != NODRIX_C_ABI_VERSION) return NODRIX_STATUS_ABI_MISMATCH;
          if (!node_type || std::strcmp(node_type, "example.passthrough") != 0)
            return NODRIX_STATUS_UNSUPPORTED;
          return nodrix::c_api::export_node(new Passthrough(), output);
        }
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
        "apiVersion": "plyctl.dev/v1",
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
        "pipeline.yaml": yaml.safe_dump(_manifest_v2(pipeline), sort_keys=False),
        "nodes/source.py": dedent(
            '''
            from plyctl import Message, SourceNode

            class CounterSource(SourceNode):
                output_types = {"output": "core.object"}
                def produce(self):
                    for sequence in range(int(self.parameters.get("count", 100))):
                        yield {"output": Message(type="core.object", payload={"value": sequence}, sequence=sequence)}
            '''
        ).lstrip(),
        "nodes/transform.py": dedent(
            '''
            from plyctl import Node

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
            from plyctl import SinkNode

            class ConsoleSink(SinkNode):
                input_types = {"input": "core.object"}
                def process(self, inputs):
                    print(inputs["input"].payload)
            """
        ).lstrip(),
        "tests/test_nodes.py": dedent(
            '''
            from plyctl import Message
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
    pipeline = dedent(
        f"""
        apiVersion: plyctl.dev/v2
        kind: Pipeline
        name: {project_name}
        profile: realtime-low-latency

        runtime:
          engine: unified
          metrics:
            enabled: true
            interval_ms: 1000
            listen: 127.0.0.1:9464

        blocks:
          source: blocks/sources/ffmpeg.yaml
          preprocess: blocks/preprocess/letterbox-320.yaml
          detector: blocks/detectors/yolo26n-ncnn.yaml
          tracker: blocks/trackers/realtime-bytetrack.yaml
          overlay: blocks/outputs/overlay.yaml
          encoder: blocks/outputs/h264.yaml

        flow:
          # Detector branch: bounded latest-frame processing.
          - from: source.frame
            to: preprocess.frame
            queue:
              capacity: 1
              policy: latest
          - from: preprocess.frame
            to: detector.frame
            queue:
              capacity: 1
              policy: latest

          # Tracker clock: every fresh source frame, with detections as a
          # slower side input. The tracker predicts between measurements.
          - from: source.frame
            to: tracker.frame
            queue:
              capacity: 2
              policy: drop_oldest
          - from: detector.detections
            to: tracker.detections
            queue:
              capacity: 1
              policy: latest

          # Exact-sequence overlay keeps a small bounded frame history.
          - from: source.frame
            to: overlay.frame
            queue:
              capacity: 4
              policy: drop_oldest
          - from: tracker.tracks
            to: overlay.tracks
            queue:
              capacity: 2
              policy: drop_oldest

          - from: overlay.frame
            to: encoder.frame
            queue:
              capacity: 1
              policy: latest

        streams:
          bind_host: 127.0.0.1
          listen_port: 7420

        publish:
          /{project_name}/preview/h264:
            from: encoder.encoded
            queue:
              capacity: 2
              policy: latest
          /{project_name}/tracks:
            from: tracker.tracks
            queue:
              capacity: 2
              policy: latest
        fragments: {{}}
        recording: {{}}
        security: {{}}
        placement: {{}}
        """
    ).lstrip()

    source = dedent(
        """
        use: media.ffmpeg_source

        # Video input. Replace this test generator with an RTSP URL or file.
        uri: lavfi:testsrc=size=640x360:rate=30

        # Decoded frame geometry and frame clock.
        width: 640
        height: 360
        fps: 30

        # RTSP: tcp is reliable; udp may reduce latency but can lose packets.
        rtsp_transport: tcp

        # Minimize FFmpeg buffering and pace generated/file input in real time.
        low_latency: true
        realtime: true
        """
    ).lstrip()

    preprocess = dedent(
        """
        use: vision.letterbox

        # Square detector input size.
        imgsz: 320
        scale_up: true
        color: [114, 114, 114]
        """
    ).lstrip()

    detector = dedent(
        """
        use: vision.ncnn_detector_native

        # Directory containing one NCNN .param/.bin pair.
        model: models/yolo26n_ncnn_model

        # Must match the preceding letterbox block.
        imgsz: 320

        # Minimum detection confidence: 0.0..1.0.
        conf: 0.18

        # IoU threshold used by native C++ NMS: 0.0..1.0.
        iou: 0.65

        # Maximum number of detections published for one frame.
        max_det: 150

        # NCNN ARM/NEON workers. No Python process isolation is required.
        backend: cpu
        threads: 4

        # Output tensor decoder: auto, xyxy, or yolo.
        output_format: auto

        # Separate objectness field: auto, true, or false.
        has_objectness: auto
        """
    ).lstrip()

    realtime_tracker = dedent(
        """
        use: vision.realtime_bytetrack

        # Source frames drive this node. The most recent detection is a
        # slower side input and is never applied twice.
        synchronization:
          policy: latest_available
          trigger_port: frame

        # Association backend: native, auto, or python. Production requires native.
        backend: native

        # Confidence threshold for primary association.
        track_thresh: 0.25

        # Minimum confidence used by the low-score recovery stage.
        low_thresh: 0.10

        # IoU threshold for primary matching.
        match_iou: 0.30

        # IoU threshold for low-score recovery matching.
        second_match_iou: 0.20

        # Frames retained before an unobserved track is deleted.
        track_buffer: 60

        # Measurement hits required before a track is published.
        min_hits: 1

        # Frames a track may remain visible using prediction only.
        max_prediction_frames: 15

        # Score multiplier applied for every prediction-only frame.
        prediction_score_decay: 0.97

        # Replay delayed measurements from their matching historical state.
        delayed_measurement_replay: true

        # Bounded history depth used by delayed-measurement replay.
        history_frames: 60

        # Measurement older than history: discard or current (approximate).
        too_old_policy: discard
        """
    ).lstrip()

    detection_tracker = dedent(
        """
        use: vision.bytetrack

        # Compatibility tracker: emits only when detections arrive.
        backend: native
        track_thresh: 0.25
        low_thresh: 0.10
        match_iou: 0.30
        second_match_iou: 0.20
        track_buffer: 30
        min_hits: 1
        """
    ).lstrip()

    overlay = dedent(
        """
        use: vision.overlay

        # Draw the persistent track identifier.
        show_track_id: true

        # Draw the object class name or numeric class ID.
        show_class: true

        # Draw the current measured or decayed prediction score.
        show_score: true
        """
    ).lstrip()

    hardware_encoder = dedent(
        """
        use: media.ffmpeg_encoder

        codec: h264
        encoder: auto

        # Probe hardware encoders first. If the platform has no encoder,
        # Plyctl reports the fallback explicitly instead of hiding it.
        acceleration: preferred

        # Applied only when the preferred policy selects a software fallback.
        preset: ultrafast
        tune: zerolatency
        crf: 23

        keyint: 30
        # fps is inherited from frame metadata.
        """
    ).lstrip()

    software_encoder = dedent(
        """
        use: media.ffmpeg_encoder

        # Explicit compatibility fallback. Select this block only after
        # accepting the CPU cost and reduced output frame rate.
        codec: h264
        encoder: libx264
        acceleration: disabled
        preset: ultrafast
        tune: zerolatency
        crf: 23
        keyint: 30
        """
    ).lstrip()

    return {
        "pipeline.yaml": pipeline,
        "requirements.txt": "plyctl[vision,media,viewer]==2.2.0a5\n",
        "blocks/sources/ffmpeg.yaml": source,
        "blocks/preprocess/letterbox-320.yaml": preprocess,
        "blocks/detectors/yolo26n-ncnn.yaml": detector,
        "blocks/trackers/realtime-bytetrack.yaml": realtime_tracker,
        "blocks/trackers/bytetrack.yaml": detection_tracker,
        "blocks/outputs/overlay.yaml": overlay,
        "blocks/outputs/h264.yaml": hardware_encoder,
        "blocks/outputs/h264-software.yaml": software_encoder,
        "models/README.md": (
            "Place one NCNN .param/.bin model pair in "
            "models/yolo26n_ncnn_model/.\n"
        ),
        "scripts/run.sh": "#!/usr/bin/env bash\nset -euo pipefail\nnodrix run\n",
        "README.md": dedent(
            f"""
            # {project_name}

            The default graph is multi-rate and hardware-first:

            ```text
            source 30 FPS ─┬─ detector latest frame (~10 FPS) ─┐
                           └─ realtime tracker frame clock ─────┤
                                                              ▼
                                                 tracks at source FPS
                                                              │
                                                     overlay → hardware H.264
            ```

            Configure each implementation in its own block YAML, then run:

            ```bash
            plyctl validate
            plyctl inspect
            plyctl run
            ```

            Discover and view from another LAN computer:

            ```bash
            plyctl stream list
            plyctl-viewer /{project_name}/preview/h264 --overlay
            ```

            Direct URI remains available:

            ```bash
            plyctl-viewer nodrix://DEVICE_IP:7420/{project_name}/preview/h264 --overlay
            ```

            The selected encoder block always probes hardware first and prints
            any software fallback explicitly. For strict hardware-only startup,
            set `acceleration: required`. For an intentional software run, use
            `blocks/outputs/h264-software.yaml`.
            """
        ).lstrip(),
    }



def _media_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "name": project_name,
        "profile": "realtime-low-latency",
        "nodes": {
            "source": {
                "use": "media.ffmpeg_source", "uri": "lavfi:testsrc=size=640x360:rate=30",
                "width": 640, "height": 360, "fps": 30, "max_frames": 90, "realtime": True,
            },
            "encoder": {"use": "media.ffmpeg_encoder", "codec": "h264", "encoder": "auto", "fps": 30, "keyint": 30},
            "writer": {"use": "media.encoded_writer", "path": "media/output.h264", "codec": "h264"},
        },
        "flow": [
            {"from": "source.frame", "to": "encoder.frame", "queue": {"capacity": 8, "policy": "block"}},
            {"from": "encoder.encoded", "to": "writer.frame", "queue": {"capacity": 8, "policy": "block"}},
        ],
        "streams": {"bind_host": "127.0.0.1"},
        "publish": {f"/{project_name}/h264": "encoder.encoded"},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(_manifest_v2(pipeline), sort_keys=False),
        "requirements.txt": "plyctl[media,viewer]==2.2.0a5\n",
        "README.md": dedent(
            f"""
            # {project_name}

            Compact Media Pack example. The selected profile supplies low-latency
            defaults, while the full recording path explicitly remains lossless.

            ```bash
            plyctl media select-encoder h264
            plyctl inspect --resolved
            plyctl run
            plyctl-viewer /{project_name}/h264
            ```
            """
        ).lstrip(),
    })

def _network_files(project_name: str) -> dict[str, str]:
    publisher = {
        "apiVersion": "plyctl.dev/v1", "kind": "Pipeline", "metadata": {"name": f"{project_name}-publisher"},
        "runtime": {"mode": "realtime", "engine": "unified"},
        "nodes": {"source": {"uses": "core.synthetic_source", "parameters": {"count": 1000000, "interval_ms": 100}}},
        "edges": [],
        "streams": {"bind_host": "127.0.0.1", "exports": [{
            "name": f"/{project_name}/events",
            "from": "source.output",
            "queue": {"capacity": 2, "policy": "latest"},
            "access": {"mode": "token", "token_env": "NODRIX_STREAM_TOKEN"},
        }]},
    }
    subscriber = {
        "apiVersion": "plyctl.dev/v1", "kind": "Pipeline", "metadata": {"name": f"{project_name}-subscriber"},
        "runtime": {"mode": "realtime", "engine": "unified"},
        "nodes": {
            "remote": {"uses": "core.stream_source", "parameters": {"name": f"/{project_name}/events", "max_messages": 5}},
            "sink": {"uses": "sink.console"},
        },
        "edges": [{"from": "remote.output", "to": "sink.input", "queue": {"capacity": 2, "policy": "latest"}}],
        "streams": {"exports": []},
    }
    return _with_native({
        "pipeline.yaml": yaml.safe_dump(_manifest_v2(publisher), sort_keys=False),
        "subscriber.yaml": yaml.safe_dump(_manifest_v2(subscriber), sort_keys=False),
        "README.md": f"# {project_name}\n\nDevice A: `plyctl run`\n\nDevice B: `plyctl stream list && plyctl run subscriber.yaml`\n",
    })

def _data_plane_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "apiVersion": "plyctl.dev/v1", "kind": "Pipeline", "metadata": {"name": project_name},
        "runtime": {
            "mode": "offline", "engine": "unified", "type_validation": "first",
            "memory": {"shared_pool": {"block_size": 1048576, "capacity": 8, "threshold": 65536}},
        },
        "nodes": {
            "source": {"uses": "./nodes/shared_source.py:SharedSource", "parameters": {"count": 100, "bytes": 262144}},
            "worker": {
                "uses": "./nodes/checksum.py:Checksum", "execution": {"isolation": "process", "cpu_affinity": []},
                "failure": {"policy": "restart_node", "max_restarts": 3, "backoff_ms": 100},
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
        "pipeline.yaml": yaml.safe_dump(_manifest_v2(pipeline), sort_keys=False),
        "nodes/shared_source.py": dedent(
            '''
            from plyctl import Message, SharedBufferPool, SourceNode

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
            from plyctl import Node

            class Checksum(Node):
                input_types = {"input": "core.bytes"}
                output_types = {"output": "core.object"}
                def process(self, inputs):
                    source = inputs["input"]
                    digest = hashlib.blake2b(source.payload.memoryview(), digest_size=8).hexdigest()
                    return {"output": source.with_updates(type="core.object", payload={"checksum": digest})}
            '''
        ).lstrip(),
        "README.md": f"# {project_name}\n\n`plyctl inspect --live` demonstrates descriptor-only shared-memory input to an isolated worker.\n",
    })


def _device_files(project_name: str) -> dict[str, str]:
    pipeline = {
        "apiVersion": "plyctl.dev/v1", "kind": "Pipeline", "metadata": {"name": project_name},
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
        "pipeline.yaml": yaml.safe_dump(_manifest_v2(pipeline), sort_keys=False),
        "nodes/device_source.py": dedent(
            '''
            from plyctl import Message, SourceNode

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
            from plyctl import SinkNode

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
        "README.md": f"# {project_name}\n\nRun `plyctl device doctor`, `plyctl inspect --memory`, then `plyctl inspect --live`. The isolated source uses executor-owned shared output buffers with zero output copies.\n",
    })


def _benchmark_files(project_name: str) -> dict[str, str]:
    files = _core_files(project_name)
    manifest = yaml.safe_load(files["pipeline.yaml"])
    manifest["metadata"]["name"] = f"{project_name}-benchmark"
    manifest["nodes"]["source"]["parameters"]["count"] = 100000
    files["pipeline.yaml"] = yaml.safe_dump(manifest, sort_keys=False)
    files["README.md"] = f"# {project_name}\n\n`plyctl benchmark --warmup 2 --repeat 5`\n"
    return files



def _package_files(project_name: str) -> dict[str, str]:
    package_name = project_name.replace("_", "-")
    return {
        "nodrix.package.yaml": yaml.safe_dump({
            "format": "nodrix-package/1",
            "name": package_name,
            "version": "1.0.0",
            "nodrix": ">=2.0,<3.0",
            "abi": 2,
            "platforms": ["any"],
            "hardware": [],
            "sandbox": "in_process",
            "nodes": {"passthrough": {"python": "python/passthrough.py:Passthrough"}},
        }, sort_keys=False),
        "python/passthrough.py": dedent(
            """
            from plyctl import Node

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
            from plyctl import Message

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
    schema_path = write_manifest_schema(directory / ".plyctl-schema.json")
    created.append(schema_path)
    return created
