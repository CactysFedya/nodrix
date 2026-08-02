from __future__ import annotations

from collections import deque
import threading
from typing import Any


class PythonBoundedQueue:
    """Close-aware bounded queue used when the native queue is unavailable."""

    def __init__(self, capacity: int, policy: str) -> None:
        if int(capacity) <= 0:
            raise ValueError("queue capacity must be positive")
        if policy not in {"block", "latest", "drop_oldest", "drop_newest"}:
            raise ValueError(f"unsupported queue policy: {policy}")
        self._capacity = int(capacity)
        self._policy = policy
        self._items: deque[Any] = deque()
        self._condition = threading.Condition()
        self._closed = False
        self._stats = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped": 0,
            "max_depth": 0,
        }

    def put(self, item: Any) -> bool:
        with self._condition:
            if self._closed:
                return False
            if self._policy == "block":
                while len(self._items) >= self._capacity and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return False
            elif self._policy == "drop_newest" and len(self._items) >= self._capacity:
                self._stats["dropped"] += 1
                return False
            elif self._policy == "latest":
                self._stats["dropped"] += len(self._items)
                self._items.clear()
            elif len(self._items) >= self._capacity:
                self._items.popleft()
                self._stats["dropped"] += 1
            self._items.append(item)
            self._stats["enqueued"] += 1
            self._stats["max_depth"] = max(
                self._stats["max_depth"], len(self._items)
            )
            self._condition.notify_all()
            return True

    def put_control(self, item: Any) -> bool:
        """Insert an ordered control item without dropping accepted data."""

        with self._condition:
            while len(self._items) >= self._capacity and not self._closed:
                self._condition.wait()
            if self._closed:
                return False
            self._items.append(item)
            self._stats["enqueued"] += 1
            self._stats["max_depth"] = max(
                self._stats["max_depth"], len(self._items)
            )
            self._condition.notify_all()
            return True

    def get(self) -> Any:
        with self._condition:
            while not self._items and not self._closed:
                self._condition.wait()
            if not self._items:
                return None
            item = self._items.popleft()
            self._stats["dequeued"] += 1
            self._condition.notify_all()
            return item

    def try_get(self) -> Any:
        with self._condition:
            if not self._items:
                return None
            item = self._items.popleft()
            self._stats["dequeued"] += 1
            self._condition.notify_all()
            return item

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def discard_pending(self) -> int:
        with self._condition:
            count = len(self._items)
            self._items.clear()
            self._stats["dropped"] += count
            self._condition.notify_all()
            return count

    def qsize(self) -> int:
        with self._condition:
            return len(self._items)

    def stats(self) -> dict[str, int]:
        with self._condition:
            return {**self._stats, "depth": len(self._items)}
