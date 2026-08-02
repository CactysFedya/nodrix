from __future__ import annotations

from collections import deque
import threading
import time
from typing import Any

from nodrix import Message, SourceNode

from ..common import load_ros_message_type
from ..context import RosNodeLease, shared_ros_runtime
from ..qos import build_qos_profile


class Ros2TopicMonitor(SourceNode):
    """Graph-only, sampled, or middleware-statistics topic monitoring."""

    output_types = {"status": "core.object"}

    def open(self, context: Any) -> None:
        super().open(context)
        self._context = context
        self._mode = str(self.parameters.get("mode", "sample")).strip().lower()
        if self._mode not in {"graph", "sample", "statistics"}:
            raise ValueError("ros2.topic_monitor mode must be graph, sample, or statistics")
        self._topic = str(self.parameters.get("topic", "")).strip()
        self._message_type_name = str(self.parameters.get("message_type", "")).strip()
        if not self._topic or not self._message_type_name:
            raise ValueError("ros2.topic_monitor requires topic and message_type")
        self._session = context.binding("session", required=False)
        self._lock = threading.Lock()
        self._arrivals: deque[float] = deque()
        self._received = 0
        self._last_arrival: float | None = None
        self._closed = False
        self._sequence = 0
        self._lease = None
        self._subscription = None
        if self._mode != "sample":
            if self._session is None or getattr(self._session, "graph", None) is None:
                raise RuntimeError(
                    "graph/statistics monitoring requires a bound ros2.session"
                )
            return
        activate = getattr(self._session, "activate_python_environment", None)
        if callable(activate):
            activate()
        self._message_class = load_ros_message_type(self._message_type_name)
        self._lease: RosNodeLease = shared_ros_runtime().acquire_node(
            name=str(self.parameters.get("node_name", f"nodrix_monitor_{context.name}")),
            namespace=str(self.parameters.get("namespace", "")),
            executor_threads=int(
                self.parameters.get(
                    "executor_threads",
                    getattr(self._session, "executor_threads", 2),
                )
            ),
        )

        def callback(_: Any) -> None:
            now = time.monotonic()
            with self._lock:
                self._received += 1
                self._last_arrival = now
                self._arrivals.append(now)

        self._subscription = self._lease.node.create_subscription(
            self._message_class,
            self._topic,
            callback,
            build_qos_profile(self.parameters),
        )

    def _sample_snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        window = max(float(self.parameters.get("window_s", 2.0)), 0.1)
        with self._lock:
            while self._arrivals and now - self._arrivals[0] > window:
                self._arrivals.popleft()
            arrivals = tuple(self._arrivals)
            received = self._received
            last = self._last_arrival
        rate = 0.0
        if len(arrivals) >= 2:
            span = arrivals[-1] - arrivals[0]
            if span > 0:
                rate = (len(arrivals) - 1) / span
        age = None if last is None else max(now - last, 0.0)
        minimum = max(float(self.parameters.get("minimum_rate_hz", 0.0)), 0.0)
        stale_timeout = max(float(self.parameters.get("stale_timeout_s", 2.0)), 0.05)
        ready = received > 0 and age is not None and age <= stale_timeout
        if minimum > 0:
            ready = ready and len(arrivals) >= 2 and rate >= minimum
        return {
            "mode": "sample",
            "topic": self._topic,
            "message_type": self._message_type_name,
            "received": received,
            "rate_hz": rate,
            "age_s": age,
            "ready": ready,
        }

    def _graph_snapshot(self) -> dict[str, Any]:
        document = self._session.graph.snapshot()
        topics = dict(document.get("topics") or {})
        state = dict(topics.get(self._topic) or {})
        types = [str(item) for item in state.get("types") or []]
        publishers = int(state.get("publishers", 0))
        updated_ns = int(document.get("updated_ns", 0) or 0)
        age_s = (
            None
            if updated_ns <= 0
            else max((time.time_ns() - updated_ns) / 1_000_000_000, 0.0)
        )
        graph_stale_timeout = max(
            float(self.parameters.get("graph_stale_timeout_s", 2.0)),
            0.05,
        )
        ready = (
            publishers > 0
            and self._message_type_name in types
            and age_s is not None
            and age_s <= graph_stale_timeout
        )
        return {
            "mode": self._mode,
            "topic": self._topic,
            "message_type": self._message_type_name,
            "types": types,
            "publishers": publishers,
            "subscribers": int(state.get("subscribers", 0)),
            "received": None,
            "rate_hz": None,
            "age_s": age_s,
            "ready": ready,
            "statistics_available": False if self._mode == "statistics" else None,
        }

    def _snapshot(self) -> dict[str, Any]:
        if self._mode == "sample":
            return self._sample_snapshot()
        return self._graph_snapshot()

    def produce(self):
        startup_timeout = max(float(self.parameters.get("startup_timeout_s", 15.0)), 0.1)
        interval = max(float(self.parameters.get("sample_interval_s", 0.5)), 0.05)
        stale_timeout = max(float(self.parameters.get("stale_timeout_s", 2.0)), 0.05)
        deadline = time.monotonic() + startup_timeout
        was_ready = False
        unhealthy_since: float | None = None
        rate_grace = max(
            float(self.parameters.get("rate_failure_grace_s", 2.0)),
            0.0,
        )
        while not self._closed:
            snapshot = self._snapshot()
            if not snapshot["ready"] and time.monotonic() >= deadline:
                raise RuntimeError(f"ROS 2 topic did not become ready: {self._topic}")
            if (
                self._mode == "sample"
                and was_ready
                and not snapshot["ready"]
            ):
                unhealthy_since = unhealthy_since or time.monotonic()
                if time.monotonic() - unhealthy_since >= rate_grace:
                    reason = (
                        "stale"
                        if snapshot["age_s"] is not None
                        and snapshot["age_s"] > stale_timeout
                        else "below the required rate"
                    )
                    raise RuntimeError(
                        f"ROS 2 topic became {reason}: {self._topic}"
                    )
            else:
                unhealthy_since = None
            was_ready = was_ready or bool(snapshot["ready"])
            yield {
                "status": Message(
                    type="core.object",
                    payload=snapshot,
                    sequence=self._sequence,
                    timestamp_ns=time.time_ns(),
                    stream_id=self._topic,
                    trace_id=self._sequence,
                )
            }
            self._sequence += 1
            time.sleep(interval)

    def health(self) -> dict[str, Any]:
        value = dict(super().health())
        if hasattr(self, "_mode"):
            value.update(self._snapshot())
        return value

    def close(self) -> None:
        self._closed = True
        lease = getattr(self, "_lease", None)
        subscription = getattr(self, "_subscription", None)
        if lease is not None and subscription is not None:
            try:
                lease.node.destroy_subscription(subscription)
            except Exception:
                pass
        if lease is not None:
            lease.close()
        self._lease = None
        super().close()
