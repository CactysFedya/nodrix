from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from plyctl import (
    Artifact,
    Resource,
    message,
    node,
    resource,
)
from nodrix.system import (
    ApplicationInstance,
    DefinitionCatalog,
    Graph,
    NodeInstance,
    ResourceInstance,
    SystemLink,
    SystemModel,
    validate_system,
)


@message(namespace="system_semantic")
@dataclass(frozen=True)
class Frame:
    value: int


@message(namespace="system_semantic")
@dataclass(frozen=True)
class Other:
    value: int


@message("compat_frame/v1", namespace="system_semantic")
@dataclass(frozen=True)
class CompatFrameV1:
    value: int


@message(
    "compat_frame/v2",
    namespace="system_semantic",
    compatible_versions=(1,),
)
@dataclass(frozen=True)
class CompatFrameV2:
    value: int


class GPU:
    pass


class NvidiaGPU(GPU):
    pass


class CPU:
    pass


@resource(name="compute.gpu", provides=GPU)
def gpu(index: int = 0):
    yield GPU()


@resource(name="compute.nvidia_gpu")
def nvidia_gpu() -> NvidiaGPU:
    return NvidiaGPU()


@resource(name="compute.generator_gpu")
def generator_gpu() -> Iterator[GPU]:
    yield GPU()


@resource(name="compute.cpu")
def cpu() -> CPU:
    return CPU()


@resource(name="compute.unknown")
def unknown_gpu():
    yield GPU()


@node(name="vision.source")
def source() -> Frame:
    return Frame(1)


@node(name="vision.detect")
def detect(image: Frame, gpu: Resource[GPU]) -> Frame:
    return image


@node(name="vision.sink")
def sink(image: Frame) -> None:
    return None


@node(name="vision.other_sink")
def other_sink(image: Other) -> None:
    return None


@node(name="vision.compat_source")
def compat_source() -> CompatFrameV1:
    return CompatFrameV1(1)


@node(name="vision.compat_sink")
def compat_sink(image: CompatFrameV2) -> None:
    return None


def _catalog() -> DefinitionCatalog:
    return DefinitionCatalog.from_definitions(
        nodes={
            "vision.source": source.__plyctl_definition__,
            "vision.detect": detect.__plyctl_definition__,
            "vision.sink": sink.__plyctl_definition__,
            "vision.other_sink": other_sink.__plyctl_definition__,
            "vision.compat_source": compat_source.__plyctl_definition__,
            "vision.compat_sink": compat_sink.__plyctl_definition__,
        },
        resources={
            "compute.gpu": gpu.__plyctl_definition__,
            "compute.nvidia_gpu": nvidia_gpu.__plyctl_definition__,
            "compute.generator_gpu": generator_gpu.__plyctl_definition__,
            "compute.cpu": cpu.__plyctl_definition__,
            "compute.unknown": unknown_gpu.__plyctl_definition__,
        },
        messages=(
            Frame.__plyctl_definition__,
            Other.__plyctl_definition__,
            CompatFrameV1.__plyctl_definition__,
            CompatFrameV2.__plyctl_definition__,
        ),
    )


def _resource_system(resource_name: str, uses: str) -> SystemModel:
    return SystemModel(
        name="resource-check",
        resources=(ResourceInstance(name=resource_name, uses=uses),),
        graphs=(
            Graph(
                name="main",
                nodes=(
                    NodeInstance(
                        name="detector",
                        uses="vision.detect",
                        resources={"gpu": resource_name},
                    ),
                ),
            ),
        ),
    )


def test_resource_definition_records_explicit_and_inferred_types() -> None:
    assert gpu.__plyctl_definition__.provided_type is GPU
    assert nvidia_gpu.__plyctl_definition__.provided_type is NvidiaGPU
    assert generator_gpu.__plyctl_definition__.provided_type is GPU
    assert unknown_gpu.__plyctl_definition__.provided_type is None


def test_resource_subclass_satisfies_node_resource_contract() -> None:
    report = validate_system(
        _resource_system("gpu0", "compute.nvidia_gpu"),
        catalog=_catalog(),
    )
    assert report.valid, report.errors
    assert not any(item.code in {"SYS126", "SYS127"} for item in report.diagnostics)


def test_resource_type_mismatch_is_rejected() -> None:
    report = validate_system(
        _resource_system("cpu0", "compute.cpu"),
        catalog=_catalog(),
    )
    assert not report.valid
    mismatch = next(item for item in report.errors if item.code == "SYS127")
    assert "GPU" in mismatch.message
    assert "CPU" in mismatch.message


def test_untyped_resource_is_warning_not_breaking_error() -> None:
    report = validate_system(
        _resource_system("gpu0", "compute.unknown"),
        catalog=_catalog(),
    )
    assert report.valid, report.errors
    warning = next(item for item in report.warnings if item.code == "SYS126")
    assert "@resource(provides=...)" in warning.message


def test_graph_to_graph_system_link_validates_port_contracts() -> None:
    system = SystemModel(
        name="links",
        graphs=(
            Graph(
                name="capture",
                nodes=(NodeInstance(name="source", uses="vision.source"),),
            ),
            Graph(
                name="perception",
                nodes=(NodeInstance(name="sink", uses="vision.sink"),),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "capture/source.output",
                    "to": "perception/sink.image",
                }
            ),
        ),
    )
    report = validate_system(system, catalog=_catalog())
    assert report.valid, report.errors


def test_graph_to_graph_system_link_rejects_contract_mismatch() -> None:
    system = SystemModel(
        name="bad-links",
        graphs=(
            Graph(
                name="capture",
                nodes=(NodeInstance(name="source", uses="vision.source"),),
            ),
            Graph(
                name="perception",
                nodes=(NodeInstance(name="sink", uses="vision.other_sink"),),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "capture/source.output",
                    "to": "perception/sink.image",
                }
            ),
        ),
    )
    report = validate_system(system, catalog=_catalog())
    assert any(item.code == "SYS143" for item in report.errors)


def test_application_boundary_with_explicit_type_is_checked() -> None:
    system = SystemModel(
        name="external",
        applications=(ApplicationInstance(name="camera", uses="camera.external"),),
        graphs=(
            Graph(
                name="perception",
                nodes=(NodeInstance(name="sink", uses="vision.sink"),),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "camera.frame",
                    "to": "perception/sink.image",
                    "type_id": Frame.__plyctl_message_type__,
                }
            ),
        ),
    )
    report = validate_system(system, catalog=_catalog())
    assert report.valid, report.errors
    assert not any(item.code == "SYS145" for item in report.warnings)


def test_application_boundary_without_type_is_explicit_warning() -> None:
    system = SystemModel(
        name="external-untyped",
        applications=(ApplicationInstance(name="camera", uses="camera.external"),),
        graphs=(
            Graph(
                name="perception",
                nodes=(NodeInstance(name="sink", uses="vision.sink"),),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "camera.frame",
                    "to": "perception/sink.image",
                }
            ),
        ),
    )
    report = validate_system(system, catalog=_catalog())
    assert report.valid, report.errors
    assert any(item.code == "SYS145" for item in report.warnings)


def test_application_boundary_wrong_explicit_type_is_rejected() -> None:
    system = SystemModel(
        name="external-wrong",
        applications=(ApplicationInstance(name="camera", uses="camera.external"),),
        graphs=(
            Graph(
                name="perception",
                nodes=(NodeInstance(name="sink", uses="vision.sink"),),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "camera.frame",
                    "to": "perception/sink.image",
                    "type_id": Other.__plyctl_message_type__,
                }
            ),
        ),
    )
    report = validate_system(system, catalog=_catalog())
    assert any(item.code == "SYS146" for item in report.errors)


def test_system_link_rejects_wrong_graph_port_direction_or_name() -> None:
    system = SystemModel(
        name="bad-port",
        graphs=(
            Graph(
                name="capture",
                nodes=(NodeInstance(name="source", uses="vision.source"),),
            ),
            Graph(
                name="perception",
                nodes=(NodeInstance(name="sink", uses="vision.sink"),),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "capture/source.missing",
                    "to": "perception/sink.image",
                }
            ),
        ),
    )
    report = validate_system(system, catalog=_catalog())
    assert any(item.code == "SYS141" for item in report.errors)


def test_artifact_producer_must_resolve_to_graph_output_port() -> None:
    valid = SystemModel(
        name="artifact-ok",
        graphs=(
            Graph(
                name="mapping",
                nodes=(NodeInstance(name="source", uses="vision.source"),),
            ),
        ),
        artifacts=(
            Artifact(
                name="frame-dump",
                kind="message",
                producer="mapping/source.output",
            ),
        ),
    )
    report = validate_system(valid, catalog=_catalog())
    assert report.valid, report.errors

    invalid = SystemModel(
        name="artifact-bad",
        graphs=valid.graphs,
        artifacts=(
            Artifact(
                name="frame-dump",
                kind="message",
                producer="mapping/source.missing",
            ),
        ),
    )
    report = validate_system(invalid, catalog=_catalog())
    assert any(item.code == "SYS161" for item in report.errors)


def test_message_compatible_versions_are_accepted_across_system_link() -> None:
    system = SystemModel(
        name="compatible",
        graphs=(
            Graph(
                name="old",
                nodes=(NodeInstance(name="source", uses="vision.compat_source"),),
            ),
            Graph(
                name="new",
                nodes=(NodeInstance(name="sink", uses="vision.compat_sink"),),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "old/source.output",
                    "to": "new/sink.image",
                }
            ),
        ),
    )
    report = validate_system(system, catalog=_catalog())
    assert report.valid, report.errors
    assert not any(item.code == "SYS143" for item in report.errors)
