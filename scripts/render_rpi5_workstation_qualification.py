#!/usr/bin/env python3
"""Render the Nodrix 2.8 two-machine qualification System.

The generated System keeps the Raspberry Pi as a remote ``process`` Target and
the workstation as a local Target.  Remote lifecycle uses the Nodrix agent;
Message data uses the independent M4 TCP transport from Pi to workstation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from nodrix.system import (
    Graph,
    NodeInstance,
    SystemLink,
    SystemModel,
    Target,
    dump_system,
    plan_system,
    validate_system,
)


def _loopback(host: str) -> bool:
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


def build_qualification_system(
    *,
    pi_agent_host: str,
    pi_agent_port: int,
    workstation_data_host: str,
    data_port: int,
    token_env: str,
    record_path: str,
    count: int,
    interval_ms: float,
    tls_ca: str | None = None,
    tls_cert: str | None = None,
    tls_key: str | None = None,
    tls_server_name: str | None = None,
) -> SystemModel:
    supplied_tls = (tls_ca is not None, tls_cert is not None, tls_key is not None)
    if any(supplied_tls) and not all(supplied_tls):
        raise ValueError("tls_ca, tls_cert and tls_key must be supplied together")
    if not _loopback(pi_agent_host) and not all(supplied_tls):
        raise ValueError("a non-loopback Pi agent requires mTLS client credentials")

    agent: dict[str, object] = {
        "host": pi_agent_host,
        "port": pi_agent_port,
        "token_env": token_env,
    }
    if all(supplied_tls):
        tls: dict[str, object] = {
            "ca_file": tls_ca,
            "cert_file": tls_cert,
            "key_file": tls_key,
        }
        if tls_server_name:
            tls["server_name"] = tls_server_name
        agent["tls"] = tls

    return SystemModel(
        name="rpi5-workstation-qualification",
        targets=(
            Target(
                name="rpi5",
                kind="host",
                properties={
                    "backend": "process",
                    "agent": agent,
                },
            ),
            Target(
                name="workstation",
                kind="host",
                properties={"backend": "local"},
            ),
        ),
        graphs=(
            Graph(
                name="robot",
                nodes=(
                    NodeInstance(
                        name="qualification_source",
                        uses="core.synthetic_source",
                        target="rpi5",
                        parameters={
                            "count": count,
                            "interval_ms": interval_ms,
                            "payload": {
                                "kind": "nodrix-2.8-pi-workstation",
                                "source": "rpi5",
                            },
                        },
                    ),
                ),
            ),
            Graph(
                name="operator",
                nodes=(
                    NodeInstance(
                        name="qualification_recorder",
                        uses="sink.jsonl",
                        target="workstation",
                        parameters={"path": record_path},
                    ),
                ),
            ),
        ),
        links=(
            SystemLink(
                **{
                    "from": "robot/qualification_source.output",
                    "to": "operator/qualification_recorder.input",
                    "uses": "tcp",
                    "parameters": {
                        "host": workstation_data_host,
                        "bind_host": "0.0.0.0",
                        "port": data_port,
                        "connect_timeout_seconds": 10.0,
                        "retry_interval_seconds": 0.1,
                    },
                }
            ),
        ),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render a Nodrix 2.8 Raspberry Pi 5 ↔ workstation qualification System."
    )
    parser.add_argument("--pi-agent-host", required=True)
    parser.add_argument("--pi-agent-port", type=int, default=7843)
    parser.add_argument(
        "--workstation-data-host",
        required=True,
        help="Workstation address reachable from the Raspberry Pi for the TCP data plane.",
    )
    parser.add_argument("--data-port", type=int, default=7850)
    parser.add_argument("--token-env", default="NODRIX_AGENT_TOKEN")
    parser.add_argument(
        "--record-path",
        default="artifacts/qualification/rpi5-workstation.jsonl",
    )
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval-ms", type=float, default=20.0)
    parser.add_argument("--tls-ca")
    parser.add_argument("--tls-cert")
    parser.add_argument("--tls-key")
    parser.add_argument("--tls-server-name")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".nodrix/qualification/rpi5-workstation.system.yaml"),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    system = build_qualification_system(
        pi_agent_host=args.pi_agent_host,
        pi_agent_port=args.pi_agent_port,
        workstation_data_host=args.workstation_data_host,
        data_port=args.data_port,
        token_env=args.token_env,
        record_path=args.record_path,
        count=args.count,
        interval_ms=args.interval_ms,
        tls_ca=args.tls_ca,
        tls_cert=args.tls_cert,
        tls_key=args.tls_key,
        tls_server_name=args.tls_server_name,
    )

    validation = validate_system(system)
    validation.raise_for_errors()
    plan_system(system)

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    dump_system(system, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
