from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np


def xywh_to_xyxy(boxes: Any) -> np.ndarray:
    """Convert center-x/center-y/width/height boxes to x1/y1/x2/y2."""
    values = np.asarray(boxes, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != 4:
        raise ValueError("boxes must have shape [N, 4]")
    result = values.copy()
    result[:, 0] = values[:, 0] - values[:, 2] * 0.5
    result[:, 1] = values[:, 1] - values[:, 3] * 0.5
    result[:, 2] = values[:, 0] + values[:, 2] * 0.5
    result[:, 3] = values[:, 1] + values[:, 3] * 0.5
    return result


def clip_boxes(boxes: Any, width: int, height: int) -> np.ndarray:
    result = np.asarray(boxes, dtype=np.float32).copy()
    if result.ndim != 2 or result.shape[1] != 4:
        raise ValueError("boxes must have shape [N, 4]")
    result[:, (0, 2)] = np.clip(result[:, (0, 2)], 0.0, float(max(width - 1, 0)))
    result[:, (1, 3)] = np.clip(result[:, (1, 3)], 0.0, float(max(height - 1, 0)))
    return result


def box_iou_matrix(first: Any, second: Any) -> np.ndarray:
    """Return pairwise IoU for two xyxy box matrices."""
    a = np.asarray(first, dtype=np.float32).reshape((-1, 4))
    b = np.asarray(second, dtype=np.float32).reshape((-1, 4))
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)

    top_left = np.maximum(a[:, None, :2], b[None, :, :2])
    bottom_right = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(bottom_right - top_left, 0.0, None)
    intersection = wh[..., 0] * wh[..., 1]

    area_a = np.clip(a[:, 2] - a[:, 0], 0.0, None) * np.clip(a[:, 3] - a[:, 1], 0.0, None)
    area_b = np.clip(b[:, 2] - b[:, 0], 0.0, None) * np.clip(b[:, 3] - b[:, 1], 0.0, None)
    union = area_a[:, None] + area_b[None, :] - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)


def nms_indices(
    boxes: Any,
    scores: Any,
    class_ids: Any,
    *,
    iou_threshold: float,
    max_detections: int,
    class_agnostic: bool = False,
) -> np.ndarray:
    """Deterministic NumPy NMS with optional class separation."""
    xyxy = np.asarray(boxes, dtype=np.float32).reshape((-1, 4))
    confidence = np.asarray(scores, dtype=np.float32).reshape((-1,))
    classes = np.asarray(class_ids, dtype=np.int32).reshape((-1,))
    if not (len(xyxy) == len(confidence) == len(classes)):
        raise ValueError("boxes, scores, and class_ids must contain the same number of items")
    if len(xyxy) == 0:
        return np.empty((0,), dtype=np.int64)

    order = np.argsort(-confidence, kind="stable")
    selected: list[int] = []
    while len(order) and len(selected) < max(0, int(max_detections)):
        current = int(order[0])
        selected.append(current)
        rest = order[1:]
        if len(rest) == 0:
            break
        overlap = box_iou_matrix(xyxy[current : current + 1], xyxy[rest])[0]
        if class_agnostic:
            suppress = overlap > float(iou_threshold)
        else:
            suppress = (overlap > float(iou_threshold)) & (classes[rest] == classes[current])
        order = rest[~suppress]
    return np.asarray(selected, dtype=np.int64)


def restore_letterbox_boxes(boxes: Any, metadata: Mapping[str, Any] | None) -> np.ndarray:
    """Map xyxy boxes from a letterboxed image back to the source frame."""
    result = np.asarray(boxes, dtype=np.float32).reshape((-1, 4)).copy()
    info = dict((metadata or {}).get("letterbox") or {})
    if not info or len(result) == 0:
        return result

    scale = float(info.get("scale", 1.0) or 1.0)
    if scale <= 0:
        raise ValueError("letterbox scale must be positive")
    pad_left = float(info.get("pad_left", 0.0))
    pad_top = float(info.get("pad_top", 0.0))
    source_width = int(info.get("source_width", 0) or 0)
    source_height = int(info.get("source_height", 0) or 0)

    result[:, (0, 2)] = (result[:, (0, 2)] - pad_left) / scale
    result[:, (1, 3)] = (result[:, (1, 3)] - pad_top) / scale
    if source_width > 0 and source_height > 0:
        result = clip_boxes(result, source_width, source_height)
    return result


def _normalize_yolo_matrix(output: Any) -> np.ndarray:
    matrix = np.asarray(output, dtype=np.float32)
    while matrix.ndim > 2 and matrix.shape[0] == 1:
        matrix = matrix[0]
    while matrix.ndim > 2 and matrix.shape[-1] == 1:
        matrix = matrix[..., 0]
    if matrix.ndim == 1:
        matrix = matrix.reshape((-1, 1))
    if matrix.ndim != 2:
        raise ValueError(f"YOLO output must reduce to a 2-D matrix, got shape {matrix.shape}")
    return np.ascontiguousarray(matrix, dtype=np.float32)


def _orient_yolo_matrix(matrix: np.ndarray, *, num_classes: int | None) -> np.ndarray:
    """Return candidates x features without losing single-candidate outputs."""
    rows, columns = matrix.shape
    expected_features: set[int] = {6}
    if num_classes is not None:
        expected_features.update({int(num_classes) + 4, int(num_classes) + 5})

    row_is_features = rows in expected_features
    column_is_features = columns in expected_features
    if row_is_features and not column_is_features:
        return np.ascontiguousarray(matrix.T, dtype=np.float32)
    if column_is_features:
        return matrix

    # Fallback for usual exported YOLO tensors such as [84, 8400].
    # Explicit num_classes is preferred because tiny test inputs can contain
    # fewer candidates than features.
    if rows <= 512 and columns > rows:
        return np.ascontiguousarray(matrix.T, dtype=np.float32)
    return matrix




def _looks_like_xyxy_score_class(matrix: np.ndarray) -> bool:
    if matrix.ndim != 2 or matrix.shape[1] != 6 or len(matrix) == 0:
        return False
    scores = matrix[:, 4]
    classes = matrix[:, 5]
    boxes = matrix[:, :4]
    finite = np.isfinite(matrix).all(axis=1)
    if not np.any(finite):
        return False
    scores = scores[finite]
    classes = classes[finite]
    boxes = boxes[finite]
    score_like = np.mean((scores >= 0.0) & (scores <= 1.0)) >= 0.95
    class_like = np.mean((classes >= 0.0) & (np.abs(classes - np.rint(classes)) <= 1e-4)) >= 0.95
    box_like = np.mean((boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])) >= 0.50
    return bool(score_like and class_like and box_like)


def decode_yolo_output(
    output: Any,
    *,
    confidence_threshold: float = 0.25,
    iou_threshold: float = 0.45,
    max_detections: int = 300,
    output_format: str = "auto",
    has_objectness: bool | str = "auto",
    num_classes: int | None = None,
    class_agnostic: bool = False,
    class_filter: Sequence[int] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decode common NCNN YOLO output layouts.

    Supported layouts:
    - ``N x 6``: x1, y1, x2, y2, score, class_id;
    - ``N x (4 + classes)``: modern Ultralytics raw output;
    - ``N x (5 + classes)``: objectness followed by class probabilities.

    Batch dimensions of size one and transposed ``features x candidates`` output
    are normalized automatically.
    """
    matrix = _orient_yolo_matrix(_normalize_yolo_matrix(output), num_classes=num_classes)
    fmt = str(output_format).strip().lower()
    if fmt not in {"auto", "xyxy_score_class", "ultralytics"}:
        raise ValueError("output_format must be auto, xyxy_score_class, or ultralytics")

    if fmt == "xyxy_score_class" or (fmt == "auto" and _looks_like_xyxy_score_class(matrix)):
        boxes = matrix[:, :4]
        scores = matrix[:, 4]
        class_ids = matrix[:, 5].astype(np.int32)
    else:
        features = int(matrix.shape[1])
        if features < 5:
            raise ValueError(f"YOLO output requires at least 5 features, got {features}")

        if isinstance(has_objectness, str):
            normalized = has_objectness.strip().lower()
            if normalized != "auto":
                has_obj = normalized in {"1", "true", "yes", "on"}
            elif num_classes is not None:
                has_obj = features == int(num_classes) + 5
            else:
                # Modern Ultralytics exports, including YOLO26 NCNN, emit
                # 4 + class probabilities. Legacy YOLOv5-style outputs can opt in.
                has_obj = False
        else:
            has_obj = bool(has_objectness)

        class_start = 5 if has_obj else 4
        class_scores = matrix[:, class_start:]
        if class_scores.shape[1] == 0:
            raise ValueError("YOLO output does not contain class scores")
        class_ids = np.argmax(class_scores, axis=1).astype(np.int32)
        scores = class_scores[np.arange(len(matrix)), class_ids]
        if has_obj:
            scores = scores * matrix[:, 4]
        boxes = xywh_to_xyxy(matrix[:, :4])

    finite = np.isfinite(boxes).all(axis=1) & np.isfinite(scores)
    valid = finite & (scores >= float(confidence_threshold))
    if class_filter is not None:
        allowed = np.asarray(tuple(int(value) for value in class_filter), dtype=np.int32)
        valid &= np.isin(class_ids, allowed)
    boxes = boxes[valid]
    scores = np.asarray(scores[valid], dtype=np.float32)
    class_ids = np.asarray(class_ids[valid], dtype=np.int32)

    if len(boxes) == 0:
        return (
            np.empty((0, 4), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
            np.empty((0,), dtype=np.int32),
        )

    positive_extent = (boxes[:, 2] > boxes[:, 0]) & (boxes[:, 3] > boxes[:, 1])
    boxes = boxes[positive_extent]
    scores = scores[positive_extent]
    class_ids = class_ids[positive_extent]
    keep = nms_indices(
        boxes,
        scores,
        class_ids,
        iou_threshold=float(iou_threshold),
        max_detections=int(max_detections),
        class_agnostic=bool(class_agnostic),
    )
    return boxes[keep], scores[keep], class_ids[keep]
