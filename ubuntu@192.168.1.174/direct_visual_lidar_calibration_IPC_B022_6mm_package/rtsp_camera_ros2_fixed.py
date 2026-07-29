#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# This variable must be set before importing cv2.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|max_delay;500000",
)

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, CompressedImage, Image


def _matrix_data(data: dict[str, Any], key: str, fallback: list[float]) -> list[float]:
    value = data.get(key)
    if isinstance(value, dict):
        raw = value.get("data")
        if isinstance(raw, list):
            return [float(x) for x in raw]
    return fallback


def load_camera_info(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None

    yaml_path = Path(path).expanduser().resolve()
    if not yaml_path.is_file():
        raise FileNotFoundError(f"Camera YAML not found: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid camera YAML: {yaml_path}")

    width = int(data.get("image_width", 0))
    height = int(data.get("image_height", 0))
    distortion_model = str(data.get("distortion_model", "plumb_bob"))

    d = _matrix_data(data, "distortion_coefficients", [])
    k = _matrix_data(data, "camera_matrix", [0.0] * 9)
    r = _matrix_data(
        data,
        "rectification_matrix",
        [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    )
    p = _matrix_data(data, "projection_matrix", [0.0] * 12)

    if len(k) != 9:
        raise ValueError("camera_matrix.data must contain 9 values")
    if len(r) != 9:
        raise ValueError("rectification_matrix.data must contain 9 values")
    if len(p) != 12:
        raise ValueError("projection_matrix.data must contain 12 values")

    return {
        "width": width,
        "height": height,
        "distortion_model": distortion_model,
        "d": d,
        "k": k,
        "r": r,
        "p": p,
        "path": str(yaml_path),
    }


def to_bgr8(frame: np.ndarray) -> np.ndarray:
    """Convert any decoded OpenCV frame to contiguous uint8 BGR."""
    if frame is None:
        raise ValueError("Decoder returned an empty frame")

    if frame.ndim == 2:
        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
    elif frame.ndim == 3 and frame.shape[2] == 4:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
    elif frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(
            f"Unsupported frame shape {frame.shape}; expected HxW, HxWx3 or HxWx4"
        )

    if frame.dtype != np.uint8:
        if np.issubdtype(frame.dtype, np.integer):
            info = np.iinfo(frame.dtype)
            scale = 255.0 / max(float(info.max), 1.0)
            frame = cv2.convertScaleAbs(frame, alpha=scale)
        else:
            finite = np.nan_to_num(frame, copy=False)
            min_value = float(np.min(finite))
            max_value = float(np.max(finite))
            if max_value > min_value:
                frame = ((finite - min_value) * (255.0 / (max_value - min_value))).astype(
                    np.uint8
                )
            else:
                frame = np.zeros(frame.shape, dtype=np.uint8)

    return np.ascontiguousarray(frame)


class RtspCameraPublisher(Node):
    def __init__(
        self,
        *,
        url: str,
        fps: float,
        frame_id: str,
        camera_yaml: str | None,
        jpeg_quality: int,
        publish_raw: bool,
    ) -> None:
        super().__init__("rtsp_camera_publisher")

        self.url = url
        self.frame_id = frame_id
        self.period = 1.0 / max(fps, 0.1)
        self.jpeg_quality = max(1, min(jpeg_quality, 100))
        self.camera_data = load_camera_info(camera_yaml)
        self.publish_raw = publish_raw

        self.raw_pub = (
            self.create_publisher(
                Image,
                "/camera/image_raw",
                qos_profile_sensor_data,
            )
            if publish_raw
            else None
        )

        self.compressed_pub = self.create_publisher(
            CompressedImage,
            "/camera/image/compressed",
            qos_profile_sensor_data,
        )

        self.info_pub = (
            self.create_publisher(
                CameraInfo,
                "/camera/camera_info",
                qos_profile_sensor_data,
            )
            if self.camera_data is not None
            else None
        )

        self.cap: cv2.VideoCapture | None = None
        self.last_resolution: tuple[int, int] | None = None
        self.last_publish_time = 0.0
        self.frames_published = 0

    def open_stream(self) -> bool:
        self.close_stream()

        safe_url = self.url.split("@")[-1]
        self.get_logger().info(f"Opening RTSP stream: ...@{safe_url}")

        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)

        # On some OpenCV builds these properties only work when supplied at open time.
        # Setting them here is harmless and helps on builds that support runtime values.
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            cap.release()
            self.get_logger().error(
                "Could not open RTSP stream. Check the URL with ffplay and close "
                "other programs that may already be using the camera stream."
            )
            return False

        self.cap = cap
        backend = cap.getBackendName() if hasattr(cap, "getBackendName") else "unknown"
        self.get_logger().info(f"RTSP stream opened; backend={backend}")
        return True

    def close_stream(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def build_camera_info(self, width: int, height: int, stamp: Any) -> CameraInfo | None:
        if self.camera_data is None:
            return None

        expected_width = int(self.camera_data["width"])
        expected_height = int(self.camera_data["height"])

        if expected_width and expected_height and (width, height) != (
            expected_width,
            expected_height,
        ):
            self.get_logger().error(
                "RTSP resolution "
                f"{width}x{height} differs from camera YAML "
                f"{expected_width}x{expected_height}. "
                "Use the exact resolution used for intrinsic calibration."
            )
            return None

        msg = CameraInfo()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        msg.width = width
        msg.height = height
        msg.distortion_model = self.camera_data["distortion_model"]
        msg.d = list(self.camera_data["d"])
        msg.k = list(self.camera_data["k"])
        msg.r = list(self.camera_data["r"])
        msg.p = list(self.camera_data["p"])
        return msg

    def build_raw_message(self, frame: np.ndarray, stamp: Any) -> Image:
        height, width = frame.shape[:2]

        msg = Image()
        msg.header.stamp = stamp
        msg.header.frame_id = self.frame_id
        msg.height = height
        msg.width = width
        msg.encoding = "bgr8"
        msg.is_bigendian = False
        msg.step = width * 3
        msg.data = frame.reshape(-1).tolist()
        return msg

    def publish_frame(self, decoded_frame: np.ndarray) -> None:
        frame = to_bgr8(decoded_frame)
        height, width = frame.shape[:2]
        resolution = (width, height)

        if resolution != self.last_resolution:
            self.get_logger().info(
                f"RTSP frame: {width}x{height}, dtype={frame.dtype}, shape={frame.shape}"
            )
            self.last_resolution = resolution

        stamp = self.get_clock().now().to_msg()

        if self.raw_pub is not None:
            self.raw_pub.publish(self.build_raw_message(frame, stamp))

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )
        if not ok:
            raise RuntimeError("OpenCV JPEG encoder returned failure")

        compressed_msg = CompressedImage()
        compressed_msg.header.stamp = stamp
        compressed_msg.header.frame_id = self.frame_id
        compressed_msg.format = "jpeg"
        compressed_msg.data = encoded.reshape(-1).tolist()
        self.compressed_pub.publish(compressed_msg)

        info_msg = self.build_camera_info(width, height, stamp)
        if info_msg is not None and self.info_pub is not None:
            self.info_pub.publish(info_msg)

        self.frames_published += 1
        if self.frames_published == 1 or self.frames_published % 20 == 0:
            self.get_logger().info(f"Published frames: {self.frames_published}")

    def run(self) -> None:
        while rclpy.ok():
            rclpy.spin_once(self, timeout_sec=0.0)

            if self.cap is None or not self.cap.isOpened():
                if not self.open_stream():
                    time.sleep(2.0)
                    continue

            assert self.cap is not None
            ok, frame = self.cap.read()

            if not ok or frame is None:
                self.get_logger().warning("RTSP frame read failed; reconnecting")
                self.close_stream()
                time.sleep(1.0)
                continue

            now = time.monotonic()
            remaining = self.period - (now - self.last_publish_time)
            if remaining > 0:
                time.sleep(remaining)

            self.publish_frame(frame)
            self.last_publish_time = time.monotonic()

    def close(self) -> None:
        self.close_stream()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish an RTSP stream as ROS 2 Image/CompressedImage topics.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("RTSP_URL"),
        help="RTSP URL. Defaults to the RTSP_URL environment variable.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=2.0,
        help="ROS publication rate. Two FPS is enough for static calibration bags.",
    )
    parser.add_argument(
        "--frame-id",
        default="camera_optical_frame",
    )
    parser.add_argument(
        "--camera-yaml",
        default=os.environ.get("CAMERA_YAML"),
        help="Optional ROS camera calibration YAML.",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=90,
    )
    parser.add_argument(
        "--publish-raw",
        action="store_true",
        help="Also publish /camera/image_raw. By default only compressed images are published.",
    )
    args = parser.parse_args()

    if not args.url:
        parser.error("Set RTSP_URL or pass --url")

    return args


def main() -> int:
    args = parse_args()
    node: RtspCameraPublisher | None = None

    try:
        rclpy.init()
        node = RtspCameraPublisher(
            url=args.url,
            fps=args.fps,
            frame_id=args.frame_id,
            camera_yaml=args.camera_yaml,
            jpeg_quality=args.jpeg_quality,
            publish_raw=args.publish_raw,
        )
        node.run()
        return 0
    except KeyboardInterrupt:
        return 0
    except BaseException as exc:
        print(
            f"\nFATAL: {type(exc).__name__}: {exc!r}\n"
            f"{traceback.format_exc()}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    finally:
        if node is not None:
            node.close()
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
