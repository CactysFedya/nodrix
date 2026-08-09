from __future__ import annotations

from dataclasses import dataclass

from nodrix.manifest import PipelineManifest
from nodrix.sdk import Resource, message, node, resource
from nodrix.system import (
    ApplicationInstance,
    Connection,
    DefinitionCatalog,
    Graph,
    NodeInstance,
    ResourceInstance,
    SystemLink,
    SystemModel,
    Target,
    pipeline_manifest_to_system,
    validate_system,
)


@message(namespace="system_test")
@dataclass(frozen=True)
class Frame:
    value: int


@message(namespace="system_test")
@dataclass(frozen=True)
class Detections:
    count: int


@message(namespace="system_test")
@dataclass(frozen=True)
class Other:
    value: int


class GPU:
    pass


@resource(name="compute.gpu")
def gpu(index: int = 0):
    yield GPU()


@node(name="vision.source")
def source() -> Frame:
    return Frame(1)


@node(name="vision.detect")
def detect(
    image: Frame,
    gpu: Resource[GPU],
    threshold: float = 0.5,
) -> Detections:
    return Detections(1)


@node(name="vision.other_sink")
def other_sink(value: Other) -> None:
    return None


def _catalog() -> DefinitionCatalog:
    return DefinitionCatalog.from_definitions(
        nodes={
            "vision.source": source.__plyctl_definition__,
            "vision.detect": detect.__plyctl_definition__,
            "vision.other_sink": other_sink.__plyctl_definition__,
        },
        resources={
            "compute.gpu": gpu.__plyctl_definition__,
        },
        messages=(
            Frame.__plyctl_definition__,
            Detections.__plyctl_definition__,
            Other.__plyctl_definition__,
        ),
    )


def test_system_model_supports_multiple_instances_of_one_definition() -> None:
    system = SystemModel(
        name="robot",
        resources=(
            ResourceInstance(name="gpu0", uses="compute.gpu", parameters={"index": 0}),
        ),
        targets=(Target(name="raspberry_pi", kind="host"),),
        graphs=(
            Graph(
                name="perception",
                nodes=(
                    NodeInstance(
                        name="source",
                        uses="vision.source",
                        target="raspberry_pi",
                    ),
                    NodeInstance(
                        name="front_detector",
                        uses="vision.detect",
                        parameters={"threshold": 0.3},
                        resources={"gpu": "gpu0"},
                        target="raspberry_pi",
                    ),
                    NodeInstance(
                        name="rear_detector",
                        uses="vision.detect",
                        parameters={"threshold": 0.6},
                        resources={"gpu": "gpu0"},
                        target="raspberry_pi",
                    ),
                ),
                connections=(
                    Connection(**{"from": "source.output", "to": "front_detector.image"}),
                    Connection(**{"from": "source.output", "to": "rear_detector.image"}),
                ),
            ),
        ),
    )

    report = validate_system(system, catalog=_catalog())
    assert report.valid, report.errors
    graph = system.graph("perception")
    assert graph.node("front_detector").uses == graph.node("rear_detector").uses
    assert graph.node("front_detector").parameters["threshold"] == 0.3
    assert graph.node("rear_detector").parameters["threshold"] == 0.6


def test_system_validation_reports_message_contract_mismatch() -> None:
    system = SystemModel(
        name="bad",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(name="source", uses="vision.source"),
                    NodeInstance(name="sink", uses="vision.other_sink"),
                ),
                connections=(
                    Connection(**{"from": "source.output", "to": "sink.value"}),
                ),
            ),
        ),
    )

    report = validate_system(system, catalog=_catalog())
    assert not report.valid
    assert any(item.code == "SYS133" for item in report.errors)


def test_system_link_connects_application_to_graph_boundary() -> None:
    system = SystemModel(
        name="mapping",
        applications=(
            ApplicationInstance(name="fastlio2", uses="ros2.fastlio2"),
        ),
        graphs=(
            Graph(
                name="mapping",
                nodes=(
                    NodeInstance(name="cloud_source", uses="vision.source"),
                ),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "fastlio2.cloud_registered",
                    "to": "mapping/cloud_source.input",
                    "uses": "ros2.topic",
                }
            ),
        ),
    )

    report = validate_system(system)
    assert report.valid, report.errors


def test_pipeline_manifest_converts_to_single_graph_system() -> None:
    manifest = PipelineManifest.model_validate(
        {
            "metadata": {"name": "legacy-pipeline", "description": "compat"},
            "runtime": {"engine": "unified"},
            "sessions": {
                "driver_session": {
                    "uses": "driver.session",
                    "parameters": {"domain": 26},
                }
            },
            "resources": {
                "lidar": {
                    "uses": "livox.device",
                    "bindings": {"session": "driver_session"},
                }
            },
            "applications": {
                "fastlio2": {
                    "uses": "ros2.application",
                    "bindings": {"lidar": "lidar"},
                }
            },
            "nodes": {
                "source": {
                    "uses": "mapping.source",
                    "bindings": {"lidar": "lidar"},
                },
                "sink": {"uses": "mapping.sink"},
            },
            "edges": [
                {"from": "source.output", "to": "sink.input"},
                {
                    "from": "fastlio2.cloud",
                    "to": "source.external",
                    "transport": {
                        "uses": "ros2.topic",
                        "parameters": {"topic": "/cloud_registered"},
                    },
                },
            ],
            "placement": {
                "default": "local",
                "nodes": {"sink": "worker"},
            },
        }
    )

    converted = pipeline_manifest_to_system(manifest)
    system = converted.system

    assert system.name == "legacy-pipeline"
    assert system.graph("main").node("source").resources["lidar"] == "lidar"
    assert system.graph("main").node("sink").target == "worker"
    assert {item.name for item in system.resources} == {"driver_session", "lidar"}
    assert system.application("fastlio2").resources["lidar"] == "lidar"
    assert system.links[0].source == "fastlio2.cloud"
    assert system.links[0].target == "main/source.external"
    assert system.links[0].uses == "ros2.topic"
    assert "runtime" in system.extensions["legacy_pipeline"]


def test_missing_resource_binding_is_rejected_when_definition_is_resolved() -> None:
    system = SystemModel(
        name="missing-resource",
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="detector",
                        uses="vision.detect",
                        parameters={"threshold": 0.5},
                    ),
                ),
            ),
        ),
    )

    report = validate_system(system, catalog=_catalog())
    assert any(item.code == "SYS124" for item in report.errors)


def test_system_model_is_exposed_on_public_plyctl_sdk() -> None:
    from plyctl import SystemModel as PublicSystemModel

    assert PublicSystemModel is SystemModel
