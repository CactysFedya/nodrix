from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from typing import Any, Callable


def _sanitize(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in name)


def prometheus_text(snapshot: dict[str, Any]) -> str:
    lines = ["# Plyctl runtime metrics"]
    for name, raw in dict(snapshot.get("nodes", {})).items():
        node = dict(raw)
        label = json.dumps(str(name))
        metrics = {
            "nodrix_node_messages_total": node.get("messages", 0),
            "nodrix_node_errors_total": node.get("errors", 0),
            "nodrix_node_rate_hz": node.get("rate_hz", 0.0),
            "nodrix_node_processing_p95_ms": node.get("p95_ms", 0.0),
            "nodrix_node_end_to_end_p95_ms": dict(node.get("end_to_end", {})).get("p95_ms", 0.0),
            "nodrix_node_restarts_total": dict(node.get("transport", {})).get("restarts", 0),
        }
        resources = dict(node.get("resources", {}))
        metrics.update({
            "nodrix_node_cpu_percent": resources.get("cpu_percent", 0.0),
            "nodrix_node_rss_bytes": resources.get("rss_bytes", 0),
            "nodrix_node_executor_rss_bytes": resources.get("executor_rss_bytes", 0),
            "nodrix_node_shared_buffer_bytes": resources.get("shared_buffer_bytes", 0),
            "nodrix_node_estimated_queue_bytes": resources.get("estimated_queue_bytes", 0),
        })
        health = dict(node.get("health", {}))
        metrics["nodrix_node_ready"] = 1 if health.get("ready") else 0
        metrics["nodrix_node_alive"] = 1 if health.get("alive") else 0
        for metric, value in metrics.items():
            lines.append(f'{metric}{{node={label}}} {float(value)}')
    for index, raw in enumerate(snapshot.get("edges", [])):
        edge = dict(raw)
        source = json.dumps(str(edge.get("source", "")))
        target = json.dumps(str(edge.get("target", "")))
        labels = f"source={source},target={target}"
        lines.append(f'nodrix_edge_dropped_total{{{labels}}} {int(edge.get("dropped", 0))}')
        lines.append(f'nodrix_edge_queue_depth{{{labels}}} {int(edge.get("depth", 0))}')
        lines.append(f'nodrix_edge_bytes_total{{{labels}}} {int(edge.get("bytes", 0))}')
    system = dict(snapshot.get("system", {}))
    for metric, key in (
        ("nodrix_system_memory_total_bytes", "memory_total_bytes"),
        ("nodrix_system_memory_available_bytes", "memory_available_bytes"),
        ("nodrix_system_temperature_c", "temperature_c"),
    ):
        if key in system:
            lines.append(f"{metric} {float(system[key])}")
    for name, raw in dict(snapshot.get("streams", {})).items():
        stream = dict(raw)
        label = json.dumps(str(name))
        lines.append(f'nodrix_stream_published_total{{stream={label}}} {int(stream.get("published", 0))}')
        lines.append(f'nodrix_stream_sent_bytes_total{{stream={label}}} {int(stream.get("sent_bytes", 0))}')
        lines.append(f'nodrix_stream_subscribers{{stream={label}}} {int(stream.get("subscribers", 0))}')
    return "\n".join(lines) + "\n"


class MetricsRecorder:
    def __init__(
        self, callback: Callable[[], dict[str, Any]], path: Path, interval: float = 1.0,
        status_path: Path | None = None,
    ) -> None:
        self.callback = callback
        self.path = path
        self.status_path = status_path
        self.interval = max(0.1, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, name="nodrix-metrics-recorder", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            record = {"timestamp_ns": time.time_ns(), **self.callback()}
            encoded = json.dumps(record, ensure_ascii=False, default=str)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
            if self.status_path is not None:
                temp = self.status_path.with_suffix(".tmp")
                temp.write_text(encoded, encoding="utf-8")
                temp.replace(self.status_path)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1.0)
            self._thread = None


class MetricsServer:
    def __init__(self, callback: Callable[[], dict[str, Any]], host: str, port: int) -> None:
        self.callback = callback
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path not in {"/", "/metrics", "/metrics.json"}:
                    self.send_error(404)
                    return
                snapshot = outer.callback()
                if self.path == "/metrics.json":
                    payload = json.dumps(snapshot, ensure_ascii=False, default=str).encode("utf-8")
                    content_type = "application/json"
                else:
                    payload = prometheus_text(snapshot).encode("utf-8")
                    content_type = "text/plain; version=0.0.4"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # A client may disconnect after reading the headers.
                    return

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name="nodrix-metrics-http", daemon=True)

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
