from __future__ import annotations

from types import SimpleNamespace

import pytest

from nodrix.errors import RuntimeGraphError
from nodrix.runtime_graph_validation import (
    validate_runtime_graph,
)


def _loaded(
    *,
    inputs=(),
    optional=(),
    connected=(),
):
    return SimpleNamespace(
        node=SimpleNamespace(
            input_types={
                name: "core.object"
                for name in inputs
            },
            optional_inputs=tuple(
                optional
            ),
        ),
        inputs={
            name: object()
            for name in connected
        },
    )


def test_empty_runtime_graph_is_valid():
    validate_runtime_graph(
        {}
    )


def test_all_required_inputs_may_be_connected():
    validate_runtime_graph(
        {
            "main.worker": _loaded(
                inputs=(
                    "left",
                    "right",
                ),
                connected=(
                    "left",
                    "right",
                ),
            ),
        }
    )


def test_unconnected_required_input_is_rejected():
    with pytest.raises(
        RuntimeGraphError,
        match=(
            r"Node 'main\.worker' "
            r"has unconnected inputs: "
            r"\['right'\]"
        ),
    ):
        validate_runtime_graph(
            {
                "main.worker": _loaded(
                    inputs=(
                        "left",
                        "right",
                    ),
                    connected=(
                        "left",
                    ),
                ),
            }
        )


def test_optional_input_may_remain_unconnected():
    validate_runtime_graph(
        {
            "main.worker": _loaded(
                inputs=(
                    "required",
                    "optional",
                ),
                optional=(
                    "optional",
                ),
                connected=(
                    "required",
                ),
            ),
        }
    )


def test_optional_input_may_also_be_connected():
    validate_runtime_graph(
        {
            "main.worker": _loaded(
                inputs=(
                    "required",
                    "optional",
                ),
                optional=(
                    "optional",
                ),
                connected=(
                    "required",
                    "optional",
                ),
            ),
        }
    )


def test_validator_does_not_require_python_source_node():
    validate_runtime_graph(
        {
            "main.worker": _loaded(
                inputs=(
                    "input",
                ),
                connected=(
                    "input",
                ),
            ),
        }
    )
