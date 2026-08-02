from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def compare_reports(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    throughput_regression: float = 0.10,
    p95_regression: float = 0.15,
) -> list[str]:
    failures: list[str] = []
    baseline_scenarios = dict(baseline.get("scenarios") or {})
    current_scenarios = dict(current.get("scenarios") or {})
    for name, expected_raw in baseline_scenarios.items():
        if name not in current_scenarios:
            failures.append(f"{name}: scenario is missing")
            continue
        expected = dict(expected_raw)
        observed = dict(current_scenarios[name])
        expected_rate = float(expected.get("throughput", 0))
        observed_rate = float(observed.get("throughput", 0))
        minimum_rate = expected_rate * (1.0 - throughput_regression)
        if observed_rate < minimum_rate:
            failures.append(
                f"{name}: throughput {observed_rate:.3f} < "
                f"{minimum_rate:.3f}"
            )
        expected_p95 = float(expected.get("p95_ms", 0))
        observed_p95 = float(observed.get("p95_ms", 0))
        if expected_p95 > 0:
            maximum_p95 = expected_p95 * (1.0 + p95_regression)
            if observed_p95 > maximum_p95:
                failures.append(
                    f"{name}: P95 {observed_p95:.3f} ms > "
                    f"{maximum_p95:.3f} ms"
                )
        if int(observed.get("unexpected_copies", 0)) > 0:
            failures.append(
                f"{name}: unexpected payload copies were observed"
            )
        if int(observed.get("memory_growth_bytes", 0)) > int(
            expected.get("max_memory_growth_bytes", 0)
        ):
            failures.append(
                f"{name}: memory growth exceeds the baseline allowance"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Plyctl benchmark output with a same-host baseline."
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument(
        "--throughput-regression",
        type=float,
        default=0.10,
    )
    parser.add_argument(
        "--p95-regression",
        type=float,
        default=0.15,
    )
    arguments = parser.parse_args()
    baseline = json.loads(
        arguments.baseline.read_text(encoding="utf-8")
    )
    current = json.loads(
        arguments.current.read_text(encoding="utf-8")
    )
    failures = compare_reports(
        baseline,
        current,
        throughput_regression=arguments.throughput_regression,
        p95_regression=arguments.p95_regression,
    )
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("Performance regression gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
