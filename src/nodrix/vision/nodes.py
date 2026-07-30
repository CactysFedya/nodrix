from __future__ import annotations

from pathlib import Path
import os
from typing import Any, Mapping, Sequence

import numpy as np
import yaml

from ..cv_types import BoxFormat, CoordinateSpace, Detections, Frame, PixelFormat, Tracks
from ..messages import Message
from ..native_plugin import NativePluginNode
from ..node import Node, NodeContext
from ..registry import register_builtin
from .geometry import decode_yolo_output, restore_letterbox_boxes
from .tracking import ByteTrackCore, RealtimeByteTrackCore, native_tracking_available

try:
    import cv2
except Exception:  # pragma: no cover - optional dependency
    cv2 = None


def _require_cv2(node_name: str) -> Any:
    if cv2 is None:
        raise RuntimeError(f"OpenCV is required for {node_name}; install nodrix[vision]")
    return cv2


def _target_size(parameters: Mapping[str, Any]) -> tuple[int, int]:
    value = parameters.get("imgsz")
    if value is not None:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values = tuple(int(item) for item in value)
            if len(values) != 2:
                raise ValueError("imgsz sequence must contain height and width")
            height, width = values
        else:
            width = height = int(value)
    else:
        width = int(parameters.get("width", 0))
        height = int(parameters.get("height", 0))
    if width <= 0 or height <= 0:
        raise ValueError("A positive imgsz or width/height is required")
    return width, height


def _resolve_path(value: str | Path, project_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_dir / path
    return path.resolve()


def resolve_ncnn_model(parameters: Mapping[str, Any], project_dir: Path) -> tuple[Path, Path]:
    explicit_param = parameters.get("param") or parameters.get("param_path")
    explicit_bin = parameters.get("bin") or parameters.get("bin_path")
    if explicit_param or explicit_bin:
        if not explicit_param or not explicit_bin:
            raise ValueError("vision.ncnn_detector requires both param and bin when either is specified")
        param_path = _resolve_path(str(explicit_param), project_dir)
        bin_path = _resolve_path(str(explicit_bin), project_dir)
    else:
        model_value = parameters.get("model")
        if not model_value:
            raise ValueError("vision.ncnn_detector requires model, or param and bin")
        model = _resolve_path(str(model_value), project_dir)
        if model.is_dir():
            params = sorted(model.glob("*.param"), key=lambda item: (not item.name.endswith(".ncnn.param"), item.name))
            bins = sorted(model.glob("*.bin"), key=lambda item: (not item.name.endswith(".ncnn.bin"), item.name))
            if len(params) != 1 or len(bins) != 1:
                raise ValueError(
                    f"NCNN model directory must contain exactly one .param and one .bin file: {model}"
                )
            param_path, bin_path = params[0], bins[0]
        elif model.suffix == ".param":
            param_path = model
            bin_path = model.with_suffix(".bin")
        elif model.suffix == ".bin":
            bin_path = model
            param_path = model.with_suffix(".param")
        else:
            candidates = [
                (Path(f"{model}.param"), Path(f"{model}.bin")),
                (Path(f"{model}.ncnn.param"), Path(f"{model}.ncnn.bin")),
            ]
            existing = [(param, binary) for param, binary in candidates if param.is_file() and binary.is_file()]
            if len(existing) != 1:
                raise ValueError(f"Cannot resolve NCNN .param/.bin pair from model={model}")
            param_path, bin_path = existing[0]

    missing = [str(path) for path in (param_path, bin_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing NCNN model file(s): " + ", ".join(missing))
    return param_path, bin_path


def _load_labels(parameters: Mapping[str, Any], project_dir: Path) -> tuple[str, ...] | None:
    direct = parameters.get("labels")
    if isinstance(direct, Mapping):
        return tuple(str(direct[key]) for key in sorted(direct, key=lambda key: int(key)))
    if isinstance(direct, Sequence) and not isinstance(direct, (str, bytes)):
        return tuple(str(value) for value in direct)

    file_value = parameters.get("labels_file")
    if not file_value:
        return None
    path = _resolve_path(str(file_value), project_dir)
    if not path.is_file():
        raise FileNotFoundError(f"Labels file does not exist: {path}")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        names = data.get("names") if isinstance(data, Mapping) else data
        if isinstance(names, Mapping):
            return tuple(str(names[key]) for key in sorted(names, key=lambda key: int(key)))
        if isinstance(names, Sequence) and not isinstance(names, (str, bytes)):
            return tuple(str(value) for value in names)
        raise ValueError(f"Labels YAML must contain a names list or mapping: {path}")
    return tuple(line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


@register_builtin("vision.letterbox")
class LetterboxNode(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"frame": "vision.frame"}
    input_memory = {"frame": ["cpu", "shared"]}
    output_memory = {"frame": "cpu"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        cv = _require_cv2("vision.letterbox")
        self.width, self.height = _target_size(self.parameters)
        self.scale_up = bool(self.parameters.get("scale_up", True))
        self.interpolation = int(self.parameters.get("interpolation", cv.INTER_LINEAR))
        color = self.parameters.get("color", [114, 114, 114])
        if isinstance(color, (int, float)):
            color = [int(color)] * 3
        if not isinstance(color, Sequence) or len(color) != 3:
            raise ValueError("letterbox color must be a scalar or three BGR values")
        self.color = tuple(int(np.clip(value, 0, 255)) for value in color)

    def process(self, inputs: dict[str, Message]) -> dict[str, Message]:
        cv = _require_cv2("vision.letterbox")
        source = inputs["frame"]
        frame = source.payload
        if not isinstance(frame, Frame):
            raise TypeError("vision.letterbox expects a nodrix.Frame payload")
        if frame.pixel_format != PixelFormat.BGR8 or frame.dtype != "uint8" or (frame.channels or 3) != 3:
            raise ValueError("vision.letterbox currently requires contiguous BGR8 uint8 frames")

        image = frame.numpy()
        scale = min(self.width / frame.width, self.height / frame.height)
        if not self.scale_up:
            scale = min(scale, 1.0)
        resized_width = max(1, int(round(frame.width * scale)))
        resized_height = max(1, int(round(frame.height * scale)))
        if resized_width == frame.width and resized_height == frame.height:
            resized = image
        else:
            resized = cv.resize(image, (resized_width, resized_height), interpolation=self.interpolation)

        pad_width = self.width - resized_width
        pad_height = self.height - resized_height
        pad_left = pad_width // 2
        pad_right = pad_width - pad_left
        pad_top = pad_height // 2
        pad_bottom = pad_height - pad_top
        output = cv.copyMakeBorder(
            resized,
            pad_top,
            pad_bottom,
            pad_left,
            pad_right,
            cv.BORDER_CONSTANT,
            value=self.color,
        )
        output = np.ascontiguousarray(output)
        letterbox = {
            "source_width": frame.width,
            "source_height": frame.height,
            "target_width": self.width,
            "target_height": self.height,
            "resized_width": resized_width,
            "resized_height": resized_height,
            "scale": float(scale),
            "pad_left": pad_left,
            "pad_top": pad_top,
            "pad_right": pad_right,
            "pad_bottom": pad_bottom,
        }
        typed = Frame.from_numpy(
            output,
            pixel_format=PixelFormat.BGR8,
            readonly=True,
            metadata={**frame.metadata, "letterbox": letterbox},
        )
        return {
            "frame": source.with_updates(
                payload=typed,
                metadata={
                    **source.metadata,
                    "width": self.width,
                    "height": self.height,
                    "letterbox": letterbox,
                },
            )
        }


def _packaged_ncnn_plugin() -> Path:
    override = os.environ.get("NODRIX_NCNN_PLUGIN")
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(
            f"NODRIX_NCNN_PLUGIN does not exist: {path}"
        )

    package_root = Path(__file__).resolve().parents[1]
    candidates = (
        package_root / "bin" / "libnodrix_ncnn_detector.so",
        package_root / "bin" / "libnodrix_ncnn_detector.dylib",
        package_root / "bin" / "nodrix_ncnn_detector.dll",
        package_root / "bin" / "nodrix_ncnn_detector.so",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        "The packaged native NCNN detector is unavailable. Install a "
        "platform wheel containing the native provider, build with "
        "NODRIX_BUILD_NCNN_PLUGIN=1, or set NODRIX_NCNN_PLUGIN. "
        "The compatible Python reference remains vision.ncnn_detector."
    )


@register_builtin("vision.ncnn_detector_native")
class NativeNcnnDetectorNode(NativePluginNode):
    """NCNN C++ inference, YOLO decoding and NMS through Plugin C ABI 2."""

    input_types = {"frame": "vision.frame"}
    output_types = {"detections": "vision.detections"}
    input_memory = {"frame": ["cpu", "shared"]}
    output_memory = {"detections": "cpu"}
    optional_inputs = frozenset()

    def __init__(self, parameters: dict[str, Any] | None = None) -> None:
        values = dict(parameters or {})
        values.setdefault("imgsz", 320)
        values.setdefault("backend", "cpu")
        values.setdefault(
            "threads",
            min(max(os.cpu_count() or 1, 1), 4),
        )
        super().__init__(
            _packaged_ncnn_plugin(),
            "vision.ncnn_detector",
            values,
            defer_host=True,
        )
        self.native_labels: tuple[str, ...] | None = None

    def open(self, context: NodeContext) -> None:
        param_path, bin_path = resolve_ncnn_model(
            self.parameters,
            context.project_dir,
        )
        self.parameters["param"] = str(param_path)
        self.parameters["bin"] = str(bin_path)
        self.native_labels = _load_labels(
            self.parameters,
            context.project_dir,
        )
        super().open(context)

    def process(
        self,
        inputs: dict[str, Message],
    ) -> dict[str, Message] | None:
        source = inputs.get("frame")
        frame = None if source is None else source.payload
        if not isinstance(frame, Frame):
            raise TypeError(
                "vision.ncnn_detector_native expects a nodrix.Frame"
            )
        width, height = _target_size(self.parameters)
        expected_stride = width * 3
        stride = frame.stride or expected_stride
        channels = frame.channels or 3
        expected_shape = (height, width, 3)
        if frame.width != width or frame.height != height:
            raise ValueError(
                "vision.ncnn_detector_native frame geometry "
                f"{frame.width}x{frame.height} does not match "
                f"configured {width}x{height}"
            )
        if frame.pixel_format != PixelFormat.BGR8:
            raise ValueError(
                "vision.ncnn_detector_native requires BGR8 input"
            )
        if frame.dtype != "uint8" or channels != 3:
            raise ValueError(
                "vision.ncnn_detector_native requires HxWx3 uint8 input"
            )
        if stride != expected_stride:
            raise ValueError(
                "vision.ncnn_detector_native requires tightly packed rows"
            )
        if frame.shape is not None and tuple(frame.shape) != expected_shape:
            raise ValueError(
                "vision.ncnn_detector_native frame shape does not match "
                f"{expected_shape}"
            )
        expected_size = height * expected_stride
        if frame.buffer.nbytes != expected_size:
            raise ValueError(
                "vision.ncnn_detector_native payload size "
                f"{frame.buffer.nbytes} does not match {expected_size}"
            )
        return super().process(inputs)

    def runtime_info(self) -> dict[str, Any]:
        return {
            "backend": "ncnn-cpp",
            "native": True,
            "threads": int(self.parameters["threads"]),
            "model": str(self.parameters.get("model", "")),
        }


@register_builtin("vision.ncnn_detector")
class NcnnDetectorNode(Node):
    input_types = {"frame": "vision.frame"}
    output_types = {"detections": "vision.detections"}
    input_memory = {"frame": ["cpu", "shared"]}
    output_memory = {"detections": "cpu"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        _require_cv2("vision.ncnn_detector")
        try:
            import ncnn  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on optional wheel
            raise RuntimeError(
                "The ncnn Python package is required for vision.ncnn_detector; "
                "install nodrix[vision-ncnn] or ncnn>=1.0.20260526"
            ) from exc

        self.ncnn = ncnn
        self.param_path, self.bin_path = resolve_ncnn_model(self.parameters, context.project_dir)
        self.labels = _load_labels(self.parameters, context.project_dir)
        self.confidence_threshold = float(self.parameters.get("conf", self.parameters.get("confidence", 0.25)))
        self.iou_threshold = float(self.parameters.get("iou", 0.45))
        self.max_detections = int(self.parameters.get("max_det", 300))
        self.output_format = str(self.parameters.get("output_format", "auto"))
        self.has_objectness = self.parameters.get("has_objectness", "auto")
        self.num_classes = self.parameters.get("num_classes")
        if self.num_classes is None and self.labels is not None:
            self.num_classes = len(self.labels)
        self.class_agnostic = bool(self.parameters.get("class_agnostic", False))
        classes = self.parameters.get("classes")
        self.class_filter = None if classes is None else tuple(int(value) for value in classes)
        self.mean = tuple(float(value) for value in self.parameters.get("mean", []))
        self.norm = tuple(float(value) for value in self.parameters.get("norm", [1 / 255.0] * 3))

        self.net = ncnn.Net()
        options = self.net.opt
        requested_backend = str(self.parameters.get("backend", "auto")).lower()
        acceleration = str(self.parameters.get("acceleration", "preferred")).lower()
        if requested_backend not in {"auto", "cpu", "vulkan"}:
            raise ValueError("vision.ncnn_detector backend must be auto, cpu, or vulkan")
        if acceleration not in {"required", "preferred", "disabled"}:
            raise ValueError("vision.ncnn_detector acceleration must be required, preferred, or disabled")
        if "use_vulkan" in self.parameters:
            requested_backend = "vulkan" if bool(self.parameters["use_vulkan"]) else "cpu"
        gpu_count = 0
        get_gpu_count = getattr(ncnn, "get_gpu_count", None)
        if callable(get_gpu_count):
            try:
                gpu_count = max(int(get_gpu_count()), 0)
            except Exception:
                gpu_count = 0
        use_vulkan = requested_backend == "vulkan" or (
            requested_backend == "auto" and acceleration != "disabled" and gpu_count > 0
        )
        if use_vulkan and gpu_count <= 0:
            raise RuntimeError("NCNN Vulkan backend was requested but no NCNN Vulkan device is available")
        if acceleration == "required" and not use_vulkan:
            raise RuntimeError(
                "Hardware acceleration is required for vision.ncnn_detector, but NCNN Vulkan is unavailable. "
                "Use acceleration: preferred only after measuring the native ARM CPU backend."
            )
        self.detector_backend = "ncnn-vulkan" if use_vulkan else "ncnn-native-cpu"
        self.acceleration_policy = acceleration
        self.gpu_count = gpu_count
        settings = {
            "num_threads": int(self.parameters.get("threads", min(max(os.cpu_count() or 1, 1), 4))),
            "use_vulkan_compute": use_vulkan,
            "lightmode": bool(self.parameters.get("lightmode", True)),
            "use_fp16_packed": bool(self.parameters.get("use_fp16_packed", True)),
            "use_fp16_storage": bool(self.parameters.get("use_fp16_storage", True)),
            "use_fp16_arithmetic": bool(self.parameters.get("use_fp16_arithmetic", False)),
        }
        for name, value in settings.items():
            if hasattr(options, name):
                setattr(options, name, value)

        param_status = self.net.load_param(str(self.param_path))
        model_status = self.net.load_model(str(self.bin_path))
        if param_status not in {None, 0} or model_status not in {None, 0}:
            raise RuntimeError(
                f"NCNN failed to load model param={self.param_path} bin={self.bin_path}: "
                f"param_status={param_status}, model_status={model_status}"
            )

        input_names = tuple(str(value) for value in getattr(self.net, "input_names", lambda: ())())
        output_names = tuple(str(value) for value in getattr(self.net, "output_names", lambda: ())())
        self.input_blob = str(self.parameters.get("input_blob") or (input_names[0] if input_names else "in0"))
        self.output_blob = str(self.parameters.get("output_blob") or (output_names[0] if output_names else "out0"))

    def _extract(self, image: np.ndarray) -> np.ndarray:
        mat_type = getattr(self.ncnn.Mat, "PixelType", self.ncnn.Mat)
        pixel_type = getattr(mat_type, "PIXEL_BGR2RGB")
        height, width = image.shape[:2]
        tensor = self.ncnn.Mat.from_pixels_resize(image, pixel_type, width, height, width, height)
        tensor.substract_mean_normalize(list(self.mean), list(self.norm))
        extractor = self.net.create_extractor()
        input_status = extractor.input(self.input_blob, tensor)
        if input_status not in {None, 0}:
            raise RuntimeError(f"NCNN extractor rejected input blob {self.input_blob!r}: {input_status}")
        extracted = extractor.extract(self.output_blob)
        if isinstance(extracted, tuple) and len(extracted) == 2:
            status, output = extracted
            if status not in {None, 0}:
                raise RuntimeError(f"NCNN extractor failed for output blob {self.output_blob!r}: {status}")
        else:
            output = extracted
        return np.asarray(output, dtype=np.float32)

    def process(self, inputs: dict[str, Message]) -> dict[str, Message]:
        source = inputs["frame"]
        frame = source.payload
        if not isinstance(frame, Frame):
            raise TypeError("vision.ncnn_detector expects a nodrix.Frame payload")
        if frame.pixel_format != PixelFormat.BGR8 or frame.dtype != "uint8" or (frame.channels or 3) != 3:
            raise ValueError("vision.ncnn_detector currently requires contiguous BGR8 uint8 frames")

        output = self._extract(frame.numpy())
        boxes, scores, class_ids = decode_yolo_output(
            output,
            confidence_threshold=self.confidence_threshold,
            iou_threshold=self.iou_threshold,
            max_detections=self.max_detections,
            output_format=self.output_format,
            has_objectness=self.has_objectness,
            num_classes=None if self.num_classes is None else int(self.num_classes),
            class_agnostic=self.class_agnostic,
            class_filter=self.class_filter,
        )
        boxes = restore_letterbox_boxes(boxes, frame.metadata)
        detections = Detections(
            boxes=boxes,
            scores=scores,
            class_ids=class_ids,
            box_format=BoxFormat.XYXY,
            coordinate_space=CoordinateSpace.PIXELS,
            labels=self.labels,
            attributes={
                "backend": self.detector_backend,
                "param": str(self.param_path),
                "bin": str(self.bin_path),
                "input_blob": self.input_blob,
                "output_blob": self.output_blob,
            },
        )
        return {
            "detections": source.with_updates(
                type="vision.detections",
                payload=detections,
                metadata={
                    **source.metadata,
                    "detections": len(detections),
                    "detector_backend": self.detector_backend,
                    "model": str(self.param_path.parent),
                },
            )
        }

    def runtime_info(self) -> dict[str, Any]:
        return {
            "backend": self.detector_backend,
            "acceleration": self.acceleration_policy,
            "gpu_count": self.gpu_count,
            "threads": int(self.parameters.get("threads", min(max(os.cpu_count() or 1, 1), 4))),
            "model": str(self.param_path.parent),
        }

    def close(self) -> None:
        self.net = None


@register_builtin("vision.bytetrack")
class ByteTrackNode(Node):
    input_types = {"detections": "vision.detections"}
    output_types = {"tracks": "vision.tracks"}
    input_memory = {"detections": ["cpu", "shared"]}
    output_memory = {"tracks": "cpu"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        self.tracker = ByteTrackCore(
            track_threshold=float(self.parameters.get("track_thresh", 0.25)),
            low_threshold=float(self.parameters.get("low_thresh", 0.10)),
            new_track_threshold=self.parameters.get("new_track_thresh"),
            match_iou=float(self.parameters.get("match_iou", 0.30)),
            second_match_iou=float(self.parameters.get("second_match_iou", 0.20)),
            track_buffer=int(self.parameters.get("track_buffer", 30)),
            minimum_hits=int(self.parameters.get("min_hits", 1)),
            maximum_visible_missed=int(self.parameters.get("max_lost_visible", 0)),
            class_agnostic=bool(self.parameters.get("class_agnostic", False)),
            process_noise=float(self.parameters.get("process_noise", 1.0)),
            measurement_noise=float(self.parameters.get("measurement_noise", 10.0)),
            backend=str(self.parameters.get("backend", "auto")),
        )

    def process(self, inputs: dict[str, Message]) -> dict[str, Message]:
        source = inputs["detections"]
        detections = source.payload
        if not isinstance(detections, Detections):
            raise TypeError("vision.bytetrack expects a nodrix.Detections payload")
        if detections.box_format != BoxFormat.XYXY or detections.coordinate_space != CoordinateSpace.PIXELS:
            raise ValueError("vision.bytetrack currently requires pixel-space XYXY boxes")
        boxes, track_ids, scores, class_ids, states = self.tracker.update(
            detections.boxes,
            detections.scores,
            detections.class_ids,
            timestamp_ns=source.timestamp_ns,
        )
        tracks = Tracks(
            boxes=boxes,
            track_ids=track_ids,
            scores=scores,
            class_ids=class_ids,
            states=states,
            box_format=BoxFormat.XYXY,
            coordinate_space=CoordinateSpace.PIXELS,
            attributes={
                "labels": None if detections.labels is None else list(detections.labels),
                "tracker": "bytetrack-kalman-iou",
            },
        )
        return {
            "tracks": source.with_updates(
                type="vision.tracks",
                payload=tracks,
                metadata={**source.metadata, "tracks": len(tracks), "tracker": "bytetrack"},
            )
        }


@register_builtin("vision.realtime_bytetrack")
class RealtimeByteTrackNode(Node):
    """Track at the frame rate while accepting slower delayed detections."""

    input_types = {"frame": "vision.frame", "detections": "vision.detections"}
    optional_inputs = frozenset({"detections"})
    output_types = {"tracks": "vision.tracks"}
    input_memory = {"frame": ["cpu", "shared"], "detections": ["cpu", "shared"]}
    output_memory = {"tracks": "cpu"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        backend = str(self.parameters.get("backend", "native"))
        if backend == "native" and not native_tracking_available():
            raise RuntimeError(
                "vision.realtime_bytetrack requires the Nodrix native C++20 tracking extension. "
                "Install a compiled Nodrix wheel/editable build, or explicitly set backend: python."
            )
        core = ByteTrackCore(
            track_threshold=float(self.parameters.get("track_thresh", 0.25)),
            low_threshold=float(self.parameters.get("low_thresh", 0.10)),
            new_track_threshold=self.parameters.get("new_track_thresh"),
            match_iou=float(self.parameters.get("match_iou", 0.30)),
            second_match_iou=float(self.parameters.get("second_match_iou", 0.20)),
            track_buffer=int(self.parameters.get("track_buffer", 60)),
            minimum_hits=int(self.parameters.get("min_hits", 1)),
            maximum_visible_missed=int(self.parameters.get("max_prediction_frames", 15)),
            class_agnostic=bool(self.parameters.get("class_agnostic", False)),
            process_noise=float(self.parameters.get("process_noise", 1.0)),
            measurement_noise=float(self.parameters.get("measurement_noise", 10.0)),
            backend=backend,
        )
        self.tracker = RealtimeByteTrackCore(
            core,
            history_frames=int(self.parameters.get("history_frames", 60)),
            maximum_prediction_frames=int(self.parameters.get("max_prediction_frames", 15)),
            prediction_score_decay=float(self.parameters.get("prediction_score_decay", 0.97)),
            delayed_measurement_replay=bool(self.parameters.get("delayed_measurement_replay", True)),
            too_old_policy=str(self.parameters.get("too_old_policy", "discard")),
        )
        self.backend = core.backend_name
        self.labels: list[str] | None = None

    def process(self, inputs: dict[str, Message]) -> dict[str, Message]:
        frame_message = inputs["frame"]
        detection_message = inputs.get("detections")
        frame = frame_message.payload
        if not isinstance(frame, Frame):
            raise TypeError("vision.realtime_bytetrack expects a nodrix.Frame payload on frame")

        step_kwargs: dict[str, Any] = {
            "frame_sequence": frame_message.sequence,
            "frame_timestamp_ns": frame_message.timestamp_ns,
        }
        if detection_message is not None:
            detections = detection_message.payload
            if not isinstance(detections, Detections):
                raise TypeError("vision.realtime_bytetrack expects nodrix.Detections on detections")
            if detections.box_format != BoxFormat.XYXY or detections.coordinate_space != CoordinateSpace.PIXELS:
                raise ValueError("vision.realtime_bytetrack requires pixel-space XYXY detections")
            if detections.labels is not None:
                self.labels = list(detections.labels)
            step_kwargs.update(
                detection_sequence=detection_message.sequence,
                detection_timestamp_ns=detection_message.timestamp_ns,
                boxes=detections.boxes,
                scores=detections.scores,
                class_ids=detections.class_ids,
            )

        current, telemetry = self.tracker.step(**step_kwargs)
        boxes, track_ids, scores, class_ids, states = current
        tracks = Tracks(
            boxes=boxes,
            track_ids=track_ids,
            scores=scores,
            class_ids=class_ids,
            states=states,
            box_format=BoxFormat.XYXY,
            coordinate_space=CoordinateSpace.PIXELS,
            attributes={
                "labels": self.labels,
                "tracker": "realtime-bytetrack",
                "backend": self.backend,
                **telemetry,
            },
        )
        return {
            "tracks": frame_message.with_updates(
                type="vision.tracks",
                payload=tracks,
                metadata={
                    **frame_message.metadata,
                    "tracks": len(tracks),
                    "tracker": "realtime-bytetrack",
                    "tracker_backend": self.backend,
                    "detector_sequence": None if detection_message is None else detection_message.sequence,
                    **telemetry,
                },
            )
        }

    def runtime_info(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "frame_clocked": True,
            "delayed_measurement_replay": self.tracker.delayed_measurement_replay,
            "history_frames": self.tracker.history.maxlen,
            "max_prediction_frames": self.tracker.maximum_prediction_frames,
        }


@register_builtin("vision.overlay")
class OverlayNode(Node):
    input_types = {"frame": "vision.frame", "tracks": "vision.tracks"}
    output_types = {"frame": "vision.frame"}
    input_memory = {"frame": ["cpu", "shared"], "tracks": ["cpu", "shared"]}
    output_memory = {"frame": "cpu"}

    def open(self, context: NodeContext) -> None:
        super().open(context)
        cv = _require_cv2("vision.overlay")
        self.thickness = max(int(self.parameters.get("thickness", 2)), 1)
        self.font_scale = max(float(self.parameters.get("font_scale", 0.5)), 0.1)
        self.show_score = bool(self.parameters.get("show_score", True))
        self.show_class = bool(self.parameters.get("show_class", True))
        self.show_track_id = bool(self.parameters.get("show_track_id", True))
        self.font = cv.FONT_HERSHEY_SIMPLEX

    @staticmethod
    def _color(track_id: int) -> tuple[int, int, int]:
        value = int(track_id) * 0x45D9F3B
        return (
            64 + ((value >> 0) & 0x7F),
            64 + ((value >> 8) & 0x7F),
            64 + ((value >> 16) & 0x7F),
        )

    def process(self, inputs: dict[str, Message]) -> dict[str, Message]:
        cv = _require_cv2("vision.overlay")
        frame_message = inputs["frame"]
        track_message = inputs["tracks"]
        frame = frame_message.payload
        tracks = track_message.payload
        if not isinstance(frame, Frame):
            raise TypeError("vision.overlay expects a nodrix.Frame payload on frame")
        if not isinstance(tracks, Tracks):
            raise TypeError("vision.overlay expects a nodrix.Tracks payload on tracks")
        if frame.pixel_format != PixelFormat.BGR8 or frame.dtype != "uint8":
            raise ValueError("vision.overlay currently requires BGR8 uint8 frames")
        if tracks.box_format != BoxFormat.XYXY or tracks.coordinate_space != CoordinateSpace.PIXELS:
            raise ValueError("vision.overlay currently requires pixel-space XYXY tracks")

        image = frame.numpy().copy()
        labels: Sequence[str] | None = None
        if isinstance(tracks.attributes, Mapping):
            configured = tracks.attributes.get("labels")
            if isinstance(configured, Sequence) and not isinstance(configured, (str, bytes)):
                labels = tuple(str(value) for value in configured)

        for box, track_id, score, class_id in zip(
            tracks.boxes,
            tracks.track_ids,
            tracks.scores,
            tracks.class_ids,
            strict=True,
        ):
            x1, y1, x2, y2 = (int(round(float(value))) for value in box)
            x1 = min(max(x1, 0), max(frame.width - 1, 0))
            y1 = min(max(y1, 0), max(frame.height - 1, 0))
            x2 = min(max(x2, 0), max(frame.width - 1, 0))
            y2 = min(max(y2, 0), max(frame.height - 1, 0))
            color = self._color(int(track_id))
            cv.rectangle(image, (x1, y1), (x2, y2), color, self.thickness)
            parts: list[str] = []
            if self.show_track_id:
                parts.append(f"#{int(track_id)}")
            if self.show_class:
                class_index = int(class_id)
                class_name = (
                    labels[class_index]
                    if labels is not None and 0 <= class_index < len(labels)
                    else str(class_index)
                )
                parts.append(class_name)
            if self.show_score:
                parts.append(f"{float(score):.2f}")
            if parts:
                text = " ".join(parts)
                (text_width, text_height), baseline = cv.getTextSize(text, self.font, self.font_scale, 1)
                text_y = max(y1, text_height + baseline + 2)
                cv.rectangle(
                    image,
                    (x1, text_y - text_height - baseline - 2),
                    (min(x1 + text_width + 4, frame.width - 1), text_y + 1),
                    color,
                    -1,
                )
                cv.putText(
                    image,
                    text,
                    (x1 + 2, text_y - baseline - 1),
                    self.font,
                    self.font_scale,
                    (0, 0, 0),
                    1,
                    cv.LINE_AA,
                )

        typed = Frame.from_numpy(
            np.ascontiguousarray(image),
            pixel_format=PixelFormat.BGR8,
            readonly=True,
            metadata={**frame.metadata, "overlay_tracks": len(tracks)},
        )
        return {
            "frame": frame_message.with_updates(
                payload=typed,
                metadata={**frame_message.metadata, "overlay_tracks": len(tracks)},
            )
        }
