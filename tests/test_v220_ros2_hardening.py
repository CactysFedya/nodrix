
from __future__ import annotations

from rich.console import Console

from nodrix.cli_project_commands import _manifest_graph_counts
from nodrix.manifest import PipelineManifest
from nodrix.ux import render_top


def test_manifest_graph_counts_include_external_transport_edges() -> None:
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "ros"},
            "runtime": {"engine": "unified"},
            "applications": {
                "driver": {"uses": "ros2.launch"},
                "mapping": {"uses": "ros2.launch"},
            },
            "nodes": {
                "health": {"uses": "ros2.topic_monitor"},
            },
            "edges": [
                {
                    "from": "driver.scan",
                    "to": "mapping.scan",
                    "transport": {
                        "uses": "ros2.topic",
                        "parameters": {
                            "topic": "/scan",
                            "message_type": (
                                "sensor_msgs/msg/LaserScan"
                            ),
                        },
                    },
                }
            ],
        }
    )

    assert _manifest_graph_counts(manifest) == {
        "nodes": 1,
        "data_plane_edges": 0,
        "external_edges": 1,
        "applications": 2,
        "total_edges": 1,
    }


def test_top_excludes_control_plane_monitor_from_bottleneck() -> None:
    console = Console(record=True, width=180)
    console.print(
        render_top(
            {
                "pipeline": "test",
                "status": "running",
                "nodes": {
                    "monitor": {
                        "rate_hz": 2.0,
                        "p95_ms": 10.0,
                        "health": {
                            "status": "healthy",
                            "participates_in_throughput": False,
                        },
                        "resources": {},
                    }
                },
                "applications": {
                    "mapping": {
                        "status": "ok",
                        "running": True,
                        "pid": 123,
                        "restart_count": 0,
                        "resources": {
                            "cpu_percent": 42.0,
                            "rss_bytes": 1024,
                            "process_count": 2,
                            "thread_count": 4,
                        },
                    }
                },
                "edges": [],
                "system": {
                    "cpu_count": 4,
                    "memory_total_bytes": 1024 * 1024,
                },
            }
        )
    )
    rendered = console.export_text()

    assert "BOTTLENECK" not in rendered
    assert "Managed applications" in rendered
    assert "mapping" in rendered
