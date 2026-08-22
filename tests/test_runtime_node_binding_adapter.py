from __future__ import annotations

from nodrix.manifest import NodeConfig
from nodrix.runtime_components import (
    runtime_node_binding_from_config,
)
from nodrix.runtime_primitives import (
    RuntimeNodeBinding,
)


def _config() -> NodeConfig:
    return NodeConfig.model_validate(
        {
            "uses": "tests.node",
            "parameters": {
                "threshold": 0.75,
            },
            "bindings": {
                "camera": "front",
            },
            "synchronization": {
                "policy": "approximate_timestamp",
                "tolerance_ms": 12.5,
                "trigger_port": "image",
                "optional_inputs": [
                    "imu",
                ],
            },
            "execution": {
                "isolation": "process",
                "cpu_affinity": [
                    2,
                    3,
                ],
                "device": "cpu",
            },
            "failure": {
                "policy": "restart_node",
                "max_restarts": 7,
                "backoff_ms": 125,
            },
            "health": {
                "timeout_ms": 750,
                "on_timeout": "restart",
            },
            "resources": {
                "memory_limit_mb": 256,
                "cpu_limit": 1.5,
                "max_message_bytes": 4096,
            },
            "memory": {
                "inputs": {
                    "image": {
                        "domain": "cpu",
                    },
                },
                "outputs": {
                    "result": {
                        "domain": "cpu",
                    },
                },
            },
        }
    )


def test_pipeline_node_config_materializes_runtime_binding():
    config = _config()

    binding = runtime_node_binding_from_config(
        config
    )

    assert isinstance(
        binding,
        RuntimeNodeBinding,
    )

    assert binding.uses == config.uses

    assert dict(
        binding.parameters
    ) == config.parameters

    assert dict(
        binding.resource_bindings
    ) == config.bindings

    assert (
        binding.synchronization_policy
        == config.synchronization.policy
    )

    assert (
        binding.synchronization_tolerance_ns
        == 12_500_000
    )

    assert (
        binding.synchronization_trigger_port
        == config.synchronization.trigger_port
    )

    assert (
        binding.synchronization_optional_inputs
        == tuple(
            config.synchronization.optional_inputs
        )
    )

    assert (
        binding.failure_policy
        == config.failure.policy
    )

    assert (
        binding.fallback_uses
        == config.failure.fallback_uses
    )

    assert (
        binding.failure_max_restarts
        == config.failure.max_restarts
    )

    assert (
        binding.failure_backoff_ms
        == config.failure.backoff_ms
    )

    assert (
        binding.health_timeout_ns
        == 750_000_000
    )

    assert (
        binding.health_on_timeout
        == config.health.on_timeout
    )

    assert (
        binding.max_message_bytes
        == config.resources.max_message_bytes
    )

    assert (
        binding.memory_limit_mb
        == config.resources.memory_limit_mb
    )

    assert (
        binding.cpu_limit
        == config.resources.cpu_limit
    )

    assert (
        binding.isolation
        == config.execution.isolation
    )

    assert (
        binding.cpu_affinity
        == tuple(
            config.execution.cpu_affinity
        )
    )

    assert (
        binding.device
        == config.execution.device
    )

    assert dict(
        binding.memory_inputs
    ) == config.memory.inputs

    assert dict(
        binding.memory_outputs
    ) == config.memory.outputs


def test_adapter_does_not_retain_node_config_object():
    config = _config()

    binding = runtime_node_binding_from_config(
        config
    )

    assert binding is not config

    assert not hasattr(
        binding,
        "model_dump",
    )

    assert not hasattr(
        binding,
        "model_validate",
    )


def test_adapter_snapshots_top_level_mappings():
    config = _config()

    binding = runtime_node_binding_from_config(
        config
    )

    original_parameters = dict(
        binding.parameters
    )

    original_bindings = dict(
        binding.resource_bindings
    )

    config.parameters[
        "later"
    ] = True

    config.bindings[
        "later"
    ] = "resource"

    assert dict(
        binding.parameters
    ) == original_parameters

    assert dict(
        binding.resource_bindings
    ) == original_bindings
