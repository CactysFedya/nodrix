from __future__ import annotations

import ast
from pathlib import Path


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


BOUNDARIES = {
    (
        "src/nodrix/"
        "extension_operation.py"
    ): "execute_foreground_operation",
    (
        "src/nodrix/"
        "workflow_operation.py"
    ): "persist_foreground_execution",
    (
        "src/nodrix/"
        "benchmark_operation.py"
    ): "persist_foreground_execution",
    (
        "src/nodrix/"
        "optimization_operation.py"
    ): "persist_foreground_execution",
}


CLI_SERVICES = {
    (
        "src/nodrix/"
        "cli_foundation_commands.py"
    ): {
        "execute_workflow_operation",
    },
    (
        "src/nodrix/"
        "cli_workspace_commands.py"
    ): {
        "execute_workflow_operation",
    },
    (
        "src/nodrix/"
        "cli_operation_commands.py"
    ): {
        "execute_benchmark_operation",
        "execute_canonical_system_benchmark",
        "execute_optimization_operation",
    },
}


def _source(
    relative: str,
) -> str:
    return (
        ROOT
        / relative
    ).read_text(
        encoding="utf-8"
    )


def _called_names(
    source: str,
) -> set[str]:
    tree = ast.parse(
        source
    )

    result: set[str] = set()

    for node in ast.walk(
        tree
    ):
        if not isinstance(
            node,
            ast.Call,
        ):
            continue

        function = node.func

        if isinstance(
            function,
            ast.Name,
        ):
            result.add(
                function.id
            )

        elif isinstance(
            function,
            ast.Attribute,
        ):
            result.add(
                function.attr
            )

    return result


def test_operation_boundaries_never_persist_runs_directly() -> None:
    for relative in BOUNDARIES:
        calls = _called_names(
            _source(
                relative
            )
        )

        assert (
            "persist_execution"
            not in calls
        ), (
            f"{relative} bypasses the "
            "canonical foreground boundary"
        )


def test_operation_boundaries_use_canonical_foreground_service() -> None:
    for (
        relative,
        required_call,
    ) in BOUNDARIES.items():
        calls = _called_names(
            _source(
                relative
            )
        )

        assert (
            required_call
            in calls
        ), (
            f"{relative} does not use "
            f"{required_call}"
        )


def test_only_foreground_boundary_calls_execution_history_persistence() -> None:
    nodrix_root = (
        ROOT
        / "src"
        / "nodrix"
    )

    callers: list[str] = []

    for path in nodrix_root.rglob(
        "*.py"
    ):
        calls = _called_names(
            path.read_text(
                encoding="utf-8"
            )
        )

        if (
            "persist_execution"
            in calls
        ):
            callers.append(
                str(
                    path.relative_to(
                        ROOT
                    )
                )
            )

    assert callers == [
        (
            "src/nodrix/"
            "foreground_operation.py"
        )
    ]


def test_cli_uses_domain_operation_services_not_run_persistence() -> None:
    forbidden = {
        "persist_execution",
        "persist_foreground_execution",
        "execute_foreground_operation",
    }

    for (
        relative,
        required_calls,
    ) in CLI_SERVICES.items():
        calls = _called_names(
            _source(
                relative
            )
        )

        assert (
            required_calls
            <= calls
        ), (
            f"{relative} does not use all "
            "canonical domain operation services"
        )

        assert forbidden.isdisjoint(
            calls
        ), (
            f"{relative} bypasses the "
            "operation service boundary"
        )
