from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from .geometry import box_iou_matrix

try:
    from .._native_tracking import greedy_iou_assignment as _native_greedy_iou_assignment
except Exception:  # pragma: no cover - extension is built in wheels/editable installs
    _native_greedy_iou_assignment = None


def native_tracking_available() -> bool:
    return _native_greedy_iou_assignment is not None


def _xyxy_to_measurement(box: np.ndarray) -> np.ndarray:
    x1, y1, x2, y2 = (float(value) for value in box)
    width = max(x2 - x1, 1e-3)
    height = max(y2 - y1, 1e-3)
    return np.asarray([x1 + width * 0.5, y1 + height * 0.5, width, height], dtype=np.float64)


def _measurement_to_xyxy(measurement: np.ndarray) -> np.ndarray:
    cx, cy, width, height = (float(value) for value in measurement[:4])
    width = max(width, 1e-3)
    height = max(height, 1e-3)
    return np.asarray(
        [cx - width * 0.5, cy - height * 0.5, cx + width * 0.5, cy + height * 0.5],
        dtype=np.float32,
    )


class BoxKalmanFilter:
    """Small constant-velocity Kalman filter for xyxy detections."""

    def __init__(self, box: Any, *, process_noise: float = 1.0, measurement_noise: float = 10.0) -> None:
        measurement = _xyxy_to_measurement(np.asarray(box, dtype=np.float32))
        self.state = np.zeros((8,), dtype=np.float64)
        self.state[:4] = measurement
        self.covariance = np.diag([10.0, 10.0, 10.0, 10.0, 100.0, 100.0, 100.0, 100.0])
        self.process_noise = max(float(process_noise), 1e-6)
        self.measurement_noise = max(float(measurement_noise), 1e-6)

    def predict(self, dt: float) -> np.ndarray:
        dt = min(max(float(dt), 1e-3), 1.0)
        transition = np.eye(8, dtype=np.float64)
        transition[:4, 4:] = np.eye(4, dtype=np.float64) * dt
        scale = self.process_noise
        q_position = scale * max(dt * dt, 1e-6)
        q_velocity = scale * max(dt, 1e-6)
        process_covariance = np.diag([q_position] * 4 + [q_velocity] * 4)
        self.state = transition @ self.state
        self.covariance = transition @ self.covariance @ transition.T + process_covariance
        self.state[2:4] = np.maximum(self.state[2:4], 1e-3)
        return self.box

    def update(self, box: Any) -> np.ndarray:
        measurement = _xyxy_to_measurement(np.asarray(box, dtype=np.float32))
        observation = np.zeros((4, 8), dtype=np.float64)
        observation[:, :4] = np.eye(4, dtype=np.float64)
        noise = np.eye(4, dtype=np.float64) * self.measurement_noise
        innovation = measurement - observation @ self.state
        innovation_covariance = observation @ self.covariance @ observation.T + noise
        gain = self.covariance @ observation.T @ np.linalg.inv(innovation_covariance)
        self.state = self.state + gain @ innovation
        identity = np.eye(8, dtype=np.float64)
        self.covariance = (identity - gain @ observation) @ self.covariance
        self.state[2:4] = np.maximum(self.state[2:4], 1e-3)
        return self.box

    @property
    def box(self) -> np.ndarray:
        return _measurement_to_xyxy(self.state)

    def snapshot(self) -> tuple[np.ndarray, np.ndarray, float, float]:
        return (
            self.state.copy(),
            self.covariance.copy(),
            self.process_noise,
            self.measurement_noise,
        )

    @classmethod
    def from_snapshot(cls, snapshot: tuple[np.ndarray, np.ndarray, float, float]) -> "BoxKalmanFilter":
        state, covariance, process_noise, measurement_noise = snapshot
        instance = cls([0.0, 0.0, 1.0, 1.0], process_noise=process_noise, measurement_noise=measurement_noise)
        instance.state = np.asarray(state, dtype=np.float64).copy()
        instance.covariance = np.asarray(covariance, dtype=np.float64).copy()
        return instance


@dataclass(slots=True)
class TrackState:
    track_id: int
    filter: BoxKalmanFilter
    score: float
    class_id: int
    hits: int = 1
    age: int = 1
    missed: int = 0
    updated: bool = True

    @property
    def box(self) -> np.ndarray:
        return self.filter.box

    def snapshot(self) -> tuple[Any, ...]:
        return (
            self.track_id,
            self.filter.snapshot(),
            self.score,
            self.class_id,
            self.hits,
            self.age,
            self.missed,
            self.updated,
        )

    @classmethod
    def from_snapshot(cls, snapshot: tuple[Any, ...]) -> "TrackState":
        track_id, filter_snapshot, score, class_id, hits, age, missed, updated = snapshot
        return cls(
            track_id=int(track_id),
            filter=BoxKalmanFilter.from_snapshot(filter_snapshot),
            score=float(score),
            class_id=int(class_id),
            hits=int(hits),
            age=int(age),
            missed=int(missed),
            updated=bool(updated),
        )


def _python_greedy_iou_assignment(
    track_boxes: np.ndarray,
    detection_boxes: np.ndarray,
    track_classes: np.ndarray,
    detection_classes: np.ndarray,
    *,
    minimum_iou: float,
    class_agnostic: bool,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    if len(track_boxes) == 0 or len(detection_boxes) == 0:
        return [], list(range(len(track_boxes))), list(range(len(detection_boxes)))
    scores = box_iou_matrix(track_boxes, detection_boxes)
    if not class_agnostic:
        scores = np.where(track_classes[:, None] == detection_classes[None, :], scores, -1.0)
    matches: list[tuple[int, int]] = []
    used_tracks: set[int] = set()
    used_detections: set[int] = set()
    while scores.size:
        flat = int(np.argmax(scores))
        track_index, detection_index = np.unravel_index(flat, scores.shape)
        value = float(scores[track_index, detection_index])
        if value < float(minimum_iou):
            break
        matches.append((int(track_index), int(detection_index)))
        used_tracks.add(int(track_index))
        used_detections.add(int(detection_index))
        scores[track_index, :] = -1.0
        scores[:, detection_index] = -1.0
    return (
        matches,
        [index for index in range(len(track_boxes)) if index not in used_tracks],
        [index for index in range(len(detection_boxes)) if index not in used_detections],
    )


def greedy_iou_assignment(
    track_boxes: Any,
    detection_boxes: Any,
    track_classes: Any,
    detection_classes: Any,
    *,
    minimum_iou: float,
    class_agnostic: bool = False,
    backend: str = "auto",
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Deterministic one-to-one IoU assignment.

    ``backend=native`` requires the C++20 extension. ``auto`` uses it when
    available and otherwise keeps the compatible NumPy implementation.
    """

    tracks = np.ascontiguousarray(np.asarray(track_boxes, dtype=np.float32).reshape((-1, 4)))
    detections = np.ascontiguousarray(np.asarray(detection_boxes, dtype=np.float32).reshape((-1, 4)))
    track_class_ids = np.ascontiguousarray(np.asarray(track_classes, dtype=np.int32).reshape((-1,)))
    detection_class_ids = np.ascontiguousarray(np.asarray(detection_classes, dtype=np.int32).reshape((-1,)))
    if backend not in {"auto", "native", "python"}:
        raise ValueError("tracking backend must be auto, native, or python")
    if backend != "python" and _native_greedy_iou_assignment is not None:
        return _native_greedy_iou_assignment(
            tracks,
            detections,
            track_class_ids,
            detection_class_ids,
            float(minimum_iou),
            bool(class_agnostic),
        )
    if backend == "native":
        raise RuntimeError(
            "Native tracking backend is unavailable. Install a Plyctl wheel or editable build "
            "that includes nodrix._native_tracking, or explicitly set backend: python."
        )
    return _python_greedy_iou_assignment(
        tracks,
        detections,
        track_class_ids,
        detection_class_ids,
        minimum_iou=minimum_iou,
        class_agnostic=class_agnostic,
    )


class TrackingCore(Protocol):
    def snapshot(self) -> Any: ...
    def restore(self, snapshot: Any) -> None: ...
    def predict(self, *, timestamp_ns: int | None = None) -> None: ...
    def correct(self, boxes: Any, scores: Any, class_ids: Any) -> None: ...
    def current(
        self,
        *,
        maximum_visible_missed: int | None = None,
        prediction_score_decay: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]: ...


class ByteTrackCore:
    """Two-stage ByteTrack association with constant-velocity prediction.

    The Kalman state stays in NumPy while the O(N*M) IoU association uses the
    native C++20 extension by default. Detection metadata is small, so this
    avoids moving image buffers or adding a device transfer solely for tracking.
    """

    def __init__(
        self,
        *,
        track_threshold: float = 0.25,
        low_threshold: float = 0.10,
        new_track_threshold: float | None = None,
        match_iou: float = 0.30,
        second_match_iou: float = 0.20,
        track_buffer: int = 30,
        minimum_hits: int = 1,
        maximum_visible_missed: int = 0,
        class_agnostic: bool = False,
        process_noise: float = 1.0,
        measurement_noise: float = 10.0,
        backend: str = "auto",
    ) -> None:
        self.track_threshold = float(track_threshold)
        self.low_threshold = float(low_threshold)
        self.new_track_threshold = float(new_track_threshold if new_track_threshold is not None else track_threshold)
        self.match_iou = float(match_iou)
        self.second_match_iou = float(second_match_iou)
        self.track_buffer = max(int(track_buffer), 0)
        self.minimum_hits = max(int(minimum_hits), 1)
        self.maximum_visible_missed = max(int(maximum_visible_missed), 0)
        self.class_agnostic = bool(class_agnostic)
        self.process_noise = float(process_noise)
        self.measurement_noise = float(measurement_noise)
        self.backend = str(backend)
        if self.backend == "native" and not native_tracking_available():
            raise RuntimeError("backend: native requires nodrix._native_tracking")
        self.tracks: list[TrackState] = []
        self.next_track_id = 1
        self.last_timestamp_ns: int | None = None

    @property
    def backend_name(self) -> str:
        if self.backend != "python" and native_tracking_available():
            return "cpp20-iou+numpy-kalman"
        return "numpy"

    def reset(self) -> None:
        self.tracks.clear()
        self.next_track_id = 1
        self.last_timestamp_ns = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "tracks": [track.snapshot() for track in self.tracks],
            "next_track_id": self.next_track_id,
            "last_timestamp_ns": self.last_timestamp_ns,
        }

    def restore(self, snapshot: dict[str, Any]) -> None:
        self.tracks = [TrackState.from_snapshot(item) for item in snapshot.get("tracks", [])]
        self.next_track_id = int(snapshot.get("next_track_id", 1))
        value = snapshot.get("last_timestamp_ns")
        self.last_timestamp_ns = None if value is None else int(value)

    def _dt(self, timestamp_ns: int | None) -> float:
        if timestamp_ns is None or self.last_timestamp_ns is None:
            dt = 1.0 / 30.0
        else:
            dt = (int(timestamp_ns) - int(self.last_timestamp_ns)) / 1e9
            if not np.isfinite(dt) or dt <= 0:
                dt = 1.0 / 30.0
        if timestamp_ns is not None:
            self.last_timestamp_ns = int(timestamp_ns)
        return min(max(float(dt), 1e-3), 1.0)

    def _create_track(self, box: np.ndarray, score: float, class_id: int) -> None:
        self.tracks.append(
            TrackState(
                track_id=self.next_track_id,
                filter=BoxKalmanFilter(
                    box,
                    process_noise=self.process_noise,
                    measurement_noise=self.measurement_noise,
                ),
                score=float(score),
                class_id=int(class_id),
            )
        )
        self.next_track_id += 1

    @staticmethod
    def _subset(array: np.ndarray, indices: list[int]) -> np.ndarray:
        if not indices:
            return array[:0]
        return array[np.asarray(indices, dtype=np.int64)]

    def _prepare_detections(self, boxes: Any, scores: Any, class_ids: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        detection_boxes = np.asarray(boxes, dtype=np.float32).reshape((-1, 4))
        detection_scores = np.asarray(scores, dtype=np.float32).reshape((-1,))
        detection_classes = np.asarray(class_ids, dtype=np.int32).reshape((-1,))
        if not (len(detection_boxes) == len(detection_scores) == len(detection_classes)):
            raise ValueError("ByteTrack inputs must have matching lengths")
        finite = np.isfinite(detection_boxes).all(axis=1) & np.isfinite(detection_scores)
        positive = (detection_boxes[:, 2] > detection_boxes[:, 0]) & (detection_boxes[:, 3] > detection_boxes[:, 1])
        valid = finite & positive & (detection_scores >= self.low_threshold)
        return detection_boxes[valid], detection_scores[valid], detection_classes[valid]

    def predict(self, *, timestamp_ns: int | None = None) -> None:
        dt = self._dt(timestamp_ns)
        for track in self.tracks:
            track.filter.predict(dt)
            track.age += 1
            track.missed += 1
            track.updated = False
        self.tracks = [track for track in self.tracks if track.missed <= self.track_buffer]

    def correct(self, boxes: Any, scores: Any, class_ids: Any) -> None:
        detection_boxes, detection_scores, detection_classes = self._prepare_detections(boxes, scores, class_ids)
        high_indices = np.flatnonzero(detection_scores >= self.track_threshold).astype(np.int64)
        low_indices = np.flatnonzero(
            (detection_scores >= self.low_threshold) & (detection_scores < self.track_threshold)
        ).astype(np.int64)
        track_boxes = np.asarray([track.box for track in self.tracks], dtype=np.float32).reshape((-1, 4))
        track_classes = np.asarray([track.class_id for track in self.tracks], dtype=np.int32)
        high_boxes = detection_boxes[high_indices]
        high_classes = detection_classes[high_indices]
        first_matches, unmatched_tracks, unmatched_high_local = greedy_iou_assignment(
            track_boxes,
            high_boxes,
            track_classes,
            high_classes,
            minimum_iou=self.match_iou,
            class_agnostic=self.class_agnostic,
            backend=self.backend,
        )
        for track_index, local_detection_index in first_matches:
            detection_index = int(high_indices[local_detection_index])
            track = self.tracks[track_index]
            track.filter.update(detection_boxes[detection_index])
            track.score = float(detection_scores[detection_index])
            track.class_id = int(detection_classes[detection_index])
            track.hits += 1
            track.missed = 0
            track.updated = True

        if unmatched_tracks and len(low_indices):
            remaining_boxes = self._subset(track_boxes, unmatched_tracks)
            remaining_classes = self._subset(track_classes, unmatched_tracks)
            low_boxes = detection_boxes[low_indices]
            low_classes = detection_classes[low_indices]
            second_matches, still_unmatched_local, _ = greedy_iou_assignment(
                remaining_boxes,
                low_boxes,
                remaining_classes,
                low_classes,
                minimum_iou=self.second_match_iou,
                class_agnostic=self.class_agnostic,
                backend=self.backend,
            )
            for local_track_index, local_detection_index in second_matches:
                track_index = unmatched_tracks[local_track_index]
                detection_index = int(low_indices[local_detection_index])
                track = self.tracks[track_index]
                track.filter.update(detection_boxes[detection_index])
                track.score = float(detection_scores[detection_index])
                track.class_id = int(detection_classes[detection_index])
                track.hits += 1
                track.missed = 0
                track.updated = True
            unmatched_tracks = [unmatched_tracks[index] for index in still_unmatched_local]

        for local_detection_index in unmatched_high_local:
            detection_index = int(high_indices[local_detection_index])
            if detection_scores[detection_index] >= self.new_track_threshold:
                self._create_track(
                    detection_boxes[detection_index],
                    float(detection_scores[detection_index]),
                    int(detection_classes[detection_index]),
                )
        self.tracks = [track for track in self.tracks if track.missed <= self.track_buffer]

    def current(
        self,
        *,
        maximum_visible_missed: int | None = None,
        prediction_score_decay: float = 1.0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
        maximum = self.maximum_visible_missed if maximum_visible_missed is None else max(int(maximum_visible_missed), 0)
        decay = min(max(float(prediction_score_decay), 0.0), 1.0)
        visible = [
            track
            for track in self.tracks
            if track.hits >= self.minimum_hits and track.missed <= maximum
        ]
        if not visible:
            return (
                np.empty((0, 4), dtype=np.float32),
                np.empty((0,), dtype=np.int64),
                np.empty((0,), dtype=np.float32),
                np.empty((0,), dtype=np.int32),
                [],
            )
        states = ["tracked" if track.updated else "predicted" for track in visible]
        scores = [track.score * (decay ** track.missed) for track in visible]
        return (
            np.asarray([track.box for track in visible], dtype=np.float32),
            np.asarray([track.track_id for track in visible], dtype=np.int64),
            np.asarray(scores, dtype=np.float32),
            np.asarray([track.class_id for track in visible], dtype=np.int32),
            states,
        )

    def update(
        self,
        boxes: Any,
        scores: Any,
        class_ids: Any,
        *,
        timestamp_ns: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
        self.predict(timestamp_ns=timestamp_ns)
        self.correct(boxes, scores, class_ids)
        return self.current()


@dataclass(slots=True)
class _HistoryEntry:
    sequence: int
    timestamp_ns: int
    before: Any
    after: Any


class RealtimeByteTrackCore:
    """Frame-clocked tracker with delayed detector measurement replay."""

    def __init__(
        self,
        tracker: TrackingCore,
        *,
        history_frames: int = 60,
        maximum_prediction_frames: int = 15,
        prediction_score_decay: float = 0.97,
        delayed_measurement_replay: bool = True,
        too_old_policy: str = "discard",
    ) -> None:
        if too_old_policy not in {"discard", "current"}:
            raise ValueError("too_old_policy must be discard or current")
        self.tracker = tracker
        self.history: deque[_HistoryEntry] = deque(maxlen=max(int(history_frames), 2))
        self.maximum_prediction_frames = max(int(maximum_prediction_frames), 0)
        self.prediction_score_decay = min(max(float(prediction_score_decay), 0.0), 1.0)
        self.delayed_measurement_replay = bool(delayed_measurement_replay)
        self.too_old_policy = too_old_policy
        self.last_frame_sequence: int | None = None
        self.last_detection_sequence: int | None = None
        self.replayed_measurements = 0
        self.discarded_measurements = 0
        self.prediction_frames = 0
        self.measurement_updates = 0

    def reset(self) -> None:
        self.history.clear()
        self.last_frame_sequence = None
        self.last_detection_sequence = None
        self.replayed_measurements = 0
        self.discarded_measurements = 0
        self.prediction_frames = 0
        self.measurement_updates = 0

    def _find_history(self, sequence: int) -> int | None:
        for index, entry in enumerate(self.history):
            if entry.sequence == sequence:
                return index
        return None

    def _apply_detection(self, sequence: int, timestamp_ns: int, boxes: Any, scores: Any, class_ids: Any) -> str:
        if self.last_detection_sequence is not None and sequence <= self.last_detection_sequence:
            return "duplicate"
        self.last_detection_sequence = sequence
        self.measurement_updates += 1
        current_sequence = self.last_frame_sequence
        if current_sequence is None or sequence == current_sequence:
            self.tracker.correct(boxes, scores, class_ids)
            return "current"

        history_index = self._find_history(sequence)
        if self.delayed_measurement_replay and history_index is not None:
            entries = list(self.history)
            target = entries[history_index]
            self.tracker.restore(target.before)
            self.tracker.predict(timestamp_ns=timestamp_ns or target.timestamp_ns)
            self.tracker.correct(boxes, scores, class_ids)
            target.after = self.tracker.snapshot()
            entries[history_index] = target
            for index in range(history_index + 1, len(entries)):
                entry = entries[index]
                entry.before = self.tracker.snapshot()
                self.tracker.predict(timestamp_ns=entry.timestamp_ns)
                entry.after = self.tracker.snapshot()
                entries[index] = entry
            self.history = deque(entries, maxlen=self.history.maxlen)
            self.replayed_measurements += 1
            return "replayed"

        if self.too_old_policy == "current":
            self.tracker.correct(boxes, scores, class_ids)
            return "current-approximate"
        self.discarded_measurements += 1
        return "discarded-too-old"

    def step(
        self,
        *,
        frame_sequence: int,
        frame_timestamp_ns: int,
        detection_sequence: int | None = None,
        detection_timestamp_ns: int | None = None,
        boxes: Any | None = None,
        scores: Any | None = None,
        class_ids: Any | None = None,
    ) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]], dict[str, Any]]:
        sequence = int(frame_sequence)
        timestamp_ns = int(frame_timestamp_ns)
        if self.last_frame_sequence is not None and sequence <= self.last_frame_sequence:
            return self.tracker.current(
                maximum_visible_missed=self.maximum_prediction_frames,
                prediction_score_decay=self.prediction_score_decay,
            ), {"measurement": "stale-frame", "prediction": False}

        before = self.tracker.snapshot()
        self.tracker.predict(timestamp_ns=timestamp_ns)
        self.prediction_frames += 1
        entry = _HistoryEntry(sequence, timestamp_ns, before, self.tracker.snapshot())
        self.history.append(entry)
        self.last_frame_sequence = sequence

        measurement = "none"
        if detection_sequence is not None and boxes is not None and scores is not None and class_ids is not None:
            measurement = self._apply_detection(
                int(detection_sequence),
                int(detection_timestamp_ns or timestamp_ns),
                boxes,
                scores,
                class_ids,
            )
            if self.history:
                self.history[-1].after = self.tracker.snapshot()

        current = self.tracker.current(
            maximum_visible_missed=self.maximum_prediction_frames,
            prediction_score_decay=self.prediction_score_decay,
        )
        return current, {
            "measurement": measurement,
            "prediction": measurement not in {"current", "replayed", "current-approximate"},
            "replayed_measurements": self.replayed_measurements,
            "discarded_measurements": self.discarded_measurements,
            "prediction_frames": self.prediction_frames,
            "measurement_updates": self.measurement_updates,
        }
