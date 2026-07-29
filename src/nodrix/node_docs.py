from __future__ import annotations

from typing import Any


NODE_PARAMETER_SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "media.ffmpeg_source": [
        {"name": "uri", "type": "string", "default": "required", "values": "file, URL, lavfi:...", "description": "Input video source."},
        {"name": "width", "type": "integer", "default": "auto", "values": ">= 1", "description": "Declared decoded width."},
        {"name": "height", "type": "integer", "default": "auto", "values": ">= 1", "description": "Declared decoded height."},
        {"name": "fps", "type": "float", "default": "source", "values": "> 0", "description": "Declared input frame rate."},
        {"name": "rtsp_transport", "type": "enum", "default": "tcp", "values": "tcp|udp", "description": "RTSP transport."},
        {"name": "low_latency", "type": "boolean", "default": "true", "values": "true|false", "description": "Enable low-latency FFmpeg flags."},
        {"name": "realtime", "type": "boolean", "default": "true", "values": "true|false", "description": "Pace generated/file input in real time."},
    ],
    "vision.letterbox": [
        {"name": "imgsz", "type": "integer", "default": "640", "values": ">= 1", "description": "Square detector input size."},
        {"name": "scale_up", "type": "boolean", "default": "true", "values": "true|false", "description": "Allow enlarging a smaller source image."},
        {"name": "color", "type": "list[int]", "default": "[114,114,114]", "values": "0..255", "description": "Padding color."},
    ],
    "vision.ncnn_detector": [
        {"name": "model", "type": "path", "default": "required", "values": "directory with .param/.bin", "description": "NCNN model directory."},
        {"name": "conf", "type": "float", "default": "0.18", "values": "0.0..1.0", "description": "Minimum detection confidence."},
        {"name": "iou", "type": "float", "default": "0.65", "values": "0.0..1.0", "description": "NMS IoU threshold."},
        {"name": "max_det", "type": "integer", "default": "150", "values": ">= 1", "description": "Maximum detections per frame."},
        {"name": "threads", "type": "integer", "default": "3", "values": ">= 1", "description": "NCNN CPU worker threads."},
        {"name": "output_format", "type": "enum", "default": "auto", "values": "auto|xyxy|yolo", "description": "Model output decoder."},
        {"name": "has_objectness", "type": "enum/bool", "default": "auto", "values": "auto|true|false", "description": "Whether output has objectness."},
    ],
    "vision.bytetrack": [
        {"name": "track_thresh", "type": "float", "default": "0.25", "values": "0.0..1.0", "description": "Primary association confidence."},
        {"name": "low_thresh", "type": "float", "default": "0.10", "values": "0.0..1.0", "description": "Recovery-stage confidence."},
        {"name": "match_iou", "type": "float", "default": "0.30", "values": "0.0..1.0", "description": "Primary IoU match threshold."},
        {"name": "second_match_iou", "type": "float", "default": "0.20", "values": "0.0..1.0", "description": "Recovery-stage IoU threshold."},
        {"name": "track_buffer", "type": "integer", "default": "30", "values": ">= 1", "description": "Frames retained for a lost track."},
        {"name": "min_hits", "type": "integer", "default": "1", "values": ">= 1", "description": "Hits required before publication."},
    ],
    "vision.overlay": [
        {"name": "show_track_id", "type": "boolean", "default": "true", "values": "true|false", "description": "Draw track IDs."},
        {"name": "show_class", "type": "boolean", "default": "true", "values": "true|false", "description": "Draw class names."},
        {"name": "show_score", "type": "boolean", "default": "true", "values": "true|false", "description": "Draw confidence scores."},
    ],
    "media.ffmpeg_encoder": [
        {"name": "codec", "type": "enum", "default": "h264", "values": "h264|h265", "description": "Output codec."},
        {"name": "encoder", "type": "string", "default": "auto", "values": "auto or FFmpeg encoder", "description": "Encoder backend."},
        {"name": "preset", "type": "string", "default": "ultrafast", "values": "FFmpeg preset", "description": "Software encoder speed preset."},
        {"name": "tune", "type": "string", "default": "zerolatency", "values": "FFmpeg tune", "description": "Software encoder tuning."},
        {"name": "crf", "type": "integer", "default": "23", "values": "0..51", "description": "Software quality target."},
        {"name": "keyint", "type": "integer", "default": "15", "values": ">= 1", "description": "Keyframe interval."},
    ],
}


def parameter_schema(reference: str) -> list[dict[str, Any]]:
    return list(NODE_PARAMETER_SCHEMAS.get(reference, ()))
