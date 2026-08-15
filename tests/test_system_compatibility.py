from __future__ import annotations

from copy import deepcopy

import pytest

from nodrix.manifest import PipelineManifest
from nodrix.system import (
    CompatibilityError,
    compatibility_report_from_system,
    dumps_system,
    loads_system,
    pipeline_manifest_to_system,
    restore_pipeline_manifest,
)


def _legacy_manifest() -> PipelineManifest:
    return PipelineManifest.model_validate(
        {
            "apiVersion": "plyctl.dev/v1",
            "kind": "Pipeline",
            "metadata": {
                "name": "legacy-complex",
                "description": "compatibility hardening fixture",
            },
            "runtime": {
                "engine": "unified",
                "mode": "realtime",
                "type_validation": "always",
                "shutdown": {
                    "mode": "graceful",
                    "timeout_ms": 5000,
                },
            },
            "sessions": {
                "driver_session": {
                    "uses": "driver.session",
                    "parameters": {"domain": 26},
                }
            },
            "resources": {
                "lidar": {
                    "uses": "livox.device",
                    "parameters": {"host": "192.168.1.174"},
                    "bindings": {"session": "driver_session"},
                }
            },
            "applications": {
                "fastlio2": {
                    "uses": "ros2.application",
                    "parameters": {"launch": "mapping.launch.py"},
                    "bindings": {"lidar": "lidar"},
                }
            },
            "nodes": {
                "source": {
                    "uses": "mapping.source",
                    "bindings": {"lidar": "lidar"},
                    "outputs": {"output": "spatial.point_cloud/v1"},
                    "synchronization": {
                        "policy": "latest_available",
                    },
                    "health": {
                        "timeout_ms": 2000,
                        "on_timeout": "report",
                    },
                },
                "sink": {
                    "uses": "mapping.sink",
                    "placement": "worker",
                    "failure": {
                        "policy": "restart_node",
                        "max_restarts": 2,
                        "backoff_ms": 100,
                    },
                },
            },
            "edges": [
                {
                    "from": "source.output",
                    "to": "sink.input",
                    "queue": {
                        "capacity": 2,
                        "policy": "latest",
                    },
                    "memory": {
                        "domain": "shared",
                        "allow_copy": False,
                    },
                },
                {
                    "from": "fastlio2.cloud",
                    "to": "source.external",
                    "transport": {
                        "uses": "ros2.topic",
                        "parameters": {"topic": "/cloud_registered"},
                    },
                },
            ],
            "links": [
                {
                    "from": "source.status",
                    "to": "fastlio2.control",
                    "uses": "ros2.service",
                    "parameters": {"service": "/mapping/control"},
                }
            ],
            "streams": {
                "exports": [
                    {
                        "name": "/mapping/output",
                        "from": "sink.output",
                        "queue": {
                            "capacity": 2,
                            "policy": "latest",
                        },
                    }
                ],
                "bind_host": "127.0.0.1",
                "listen_port": 0,
            },
            "fragments": {
                "postprocess": {
                    "version": "1.0.0",
                    "nodes": {
                        "inner": {
                            "uses": "mapping.postprocess",
                        }
                    },
                }
            },
            "recording": {
                "enabled": True,
                "streams": ["/mapping/output"],
                "directory": "recordings",
                "checkpoint_records": 64,
                "durable": True,
                "queue_capacity": 32,
            },
            "security": {
                "require_signed_plugins": True,
                "allow_unsigned_local_plugins": False,
                "native_plugin_allowlist": ["mapping.native"],
                "reject_world_writable_plugins": True,
                "secret_providers": ["environment"],
            },
            "placement": {
                "default": "local",
                "nodes": {
                    "sink": "worker",
                },
            },
        }
    )


def _dump_manifest(manifest: PipelineManifest) -> dict:
    return manifest.model_dump(
        by_alias=True,
        exclude_none=True,
        mode="json",
    )


def test_complex_pipeline_conversion_is_lossless_and_reversible() -> None:
    manifest = _legacy_manifest()
    converted = pipeline_manifest_to_system(manifest)

    assert converted.lossless
    assert converted.reversible
    assert converted.report.lossless
    assert converted.report.unsupported == ()
    assert converted.report.counts["transformed"] > 0
    assert converted.report.counts["deferred"] > 0

    restored = restore_pipeline_manifest(converted.system)
    assert _dump_manifest(restored) == _dump_manifest(manifest)


def test_compatibility_report_covers_all_pipeline_sections() -> None:
    converted = pipeline_manifest_to_system(_legacy_manifest())

    expected = {
        "apiVersion",
        "kind",
        "metadata",
        "runtime",
        "sessions",
        "resources",
        "applications",
        "nodes",
        "edges",
        "links",
        "streams",
        "fragments",
        "recording",
        "security",
        "placement",
    }
    assert set(converted.report.covered_sections) == expected

    dispositions = {
        entry.path: entry.disposition
        for entry in converted.report.entries
    }
    assert dispositions["runtime"] == "deferred"
    assert dispositions["streams"] == "deferred"
    assert dispositions["fragments"] == "deferred"
    assert dispositions["recording"] == "deferred"
    assert dispositions["security"] == "deferred"
    assert dispositions["placement"] == "transformed"


def test_report_and_snapshot_survive_system_yaml_round_trip() -> None:
    converted = pipeline_manifest_to_system(_legacy_manifest())

    text = dumps_system(converted.system, format="yaml")
    loaded = loads_system(text, format="yaml")

    restored = restore_pipeline_manifest(loaded)
    assert _dump_manifest(restored) == _dump_manifest(_legacy_manifest())

    persisted_report = compatibility_report_from_system(loaded)
    assert persisted_report.source_sha256 == converted.report.source_sha256
    assert persisted_report.counts == converted.report.counts
    assert persisted_report.lossless


def test_snapshot_digest_detects_tampering() -> None:
    converted = pipeline_manifest_to_system(_legacy_manifest())
    extensions = deepcopy(dict(converted.system.extensions))
    legacy = dict(extensions["legacy_pipeline"])
    legacy["source_manifest_json"] += " "
    extensions["legacy_pipeline"] = legacy
    tampered = converted.system.model_copy(
        update={"extensions": extensions}
    )

    with pytest.raises(CompatibilityError) as exc_info:
        restore_pipeline_manifest(tampered)

    assert exc_info.value.code == "COMPAT405"


def test_old_compatibility_warnings_remain_available() -> None:
    converted = pipeline_manifest_to_system(_legacy_manifest())
    codes = {warning.code for warning in converted.warnings}

    assert {"COMPAT201", "COMPAT202", "COMPAT203"} <= codes


def test_conversion_retains_execution_specific_details_for_future_2_6() -> None:
    manifest = _legacy_manifest()
    converted = pipeline_manifest_to_system(manifest)

    graph = converted.system.graph("main")
    source = graph.node("source")
    sink = graph.node("sink")

    assert source.extensions["legacy"]["synchronization"]["policy"] == "latest_available"
    assert source.extensions["legacy"]["health"]["timeout_ms"] == 2000
    assert sink.extensions["legacy"]["failure"]["policy"] == "restart_node"

    local_edge = graph.connections[0]
    assert local_edge.extensions["legacy"]["queue"]["policy"] == "latest"
    assert local_edge.extensions["legacy"]["memory"]["domain"] == "shared"

    legacy = converted.system.extensions["legacy_pipeline"]
    assert legacy["runtime"]["mode"] == "realtime"
    assert legacy["recording"]["enabled"] is True
    assert legacy["security"]["require_signed_plugins"] is True


def test_report_is_publicly_exposed_through_plyctl() -> None:
    from plyctl import CompatibilityReport as PublicCompatibilityReport
    from plyctl import restore_pipeline_manifest as public_restore

    converted = pipeline_manifest_to_system(_legacy_manifest())

    assert PublicCompatibilityReport is type(converted.report)
    assert public_restore is restore_pipeline_manifest
