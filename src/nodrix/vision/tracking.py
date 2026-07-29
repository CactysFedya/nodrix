from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .geometry import box_iou_matrix


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


def greedy_iou_assignment(
    track_boxes: Any,
    detection_boxes: Any,
    track_classes: Any,
    detection_classes: Any,
    *,
    minimum_iou: float,
    class_agnostic: bool = False,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Deterministic one-to-one IoU assignment without a SciPy dependency."""
    tracks = np.asarray(track_boxes, dtype=np.float32).reshape((-1, 4))
    detections = np.asarray(detection_boxes, dtype=np.float32).reshape((-1, 4))
    track_class_ids = np.asarray(track_classes, dtype=np.int32).reshape((-1,))
    detection_class_ids = np.asarray(detection_classes, dtype=np.int32).reshape((-1,))
    if len(tracks) == 0 or len(detections) == 0:
        return [], list(range(len(tracks))), list(range(len(detections)))

    scores = box_iou_matrix(tracks, detections)
    if not class_agnostic:
        scores = np.where(track_class_ids[:, None] == detection_class_ids[None, :], scores, -1.0)

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

    unmatched_tracks = [index for index in range(len(tracks)) if index not in used_tracks]
    unmatched_detections = [index for index in range(len(detections)) if index not in used_detections]
    return matches, unmatched_tracks, unmatched_detections


class ByteTrackCore:
    """Two-stage ByteTrack-style association with a constant-velocity filter.

    The implementation intentionally avoids SciPy/lap so it can run on edge
    devices with only NumPy installed. High-confidence detections are matched
    first, then low-confidence detections recover unmatched tracks.
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
        self.tracks: list[TrackState] = []
        self.next_track_id = 1
        self.last_timestamp_ns: int | None = None

    def reset(self) -> None:
        self.tracks.clear()
        self.next_track_id = 1
        self.last_timestamp_ns = None

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

    def update(
        self,
        boxes: Any,
        scores: Any,
        class_ids: Any,
        *,
        timestamp_ns: int | None = None,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
        detection_boxes = np.asarray(boxes, dtype=np.float32).reshape((-1, 4))
        detection_scores = np.asarray(scores, dtype=np.float32).reshape((-1,))
        detection_classes = np.asarray(class_ids, dtype=np.int32).reshape((-1,))
        if not (len(detection_boxes) == len(detection_scores) == len(detection_classes)):
            raise ValueError("ByteTrack inputs must have matching lengths")

        finite = np.isfinite(detection_boxes).all(axis=1) & np.isfinite(detection_scores)
        positive = (detection_boxes[:, 2] > detection_boxes[:, 0]) & (detection_boxes[:, 3] > detection_boxes[:, 1])
        valid = finite & positive & (detection_scores >= self.low_threshold)
        detection_boxes = detection_boxes[valid]
        detection_scores = detection_scores[valid]
        detection_classes = detection_classes[valid]

        dt = self._dt(timestamp_ns)
        for track in self.tracks:
            track.filter.predict(dt)
            track.age += 1
            track.missed += 1
            track.updated = False

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
        visible = [
            track
            for track in self.tracks
            if track.hits >= self.minimum_hits and track.missed <= self.maximum_visible_missed
        ]
        if not visible:
            return (
                np.empty((0, 4), dtype=np.float32),
                np.empty((0,), dtype=np.int64),
                np.empty((0,), dtype=np.float32),
                np.empty((0,), dtype=np.int32),
                [],
            )

        states = ["tracked" if track.updated else "lost" for track in visible]
        return (
            np.asarray([track.box for track in visible], dtype=np.float32),
            np.asarray([track.track_id for track in visible], dtype=np.int64),
            np.asarray([track.score for track in visible], dtype=np.float32),
            np.asarray([track.class_id for track in visible], dtype=np.int32),
            states,
        )
