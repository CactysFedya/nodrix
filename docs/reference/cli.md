# CLI reference

The public command is `plyctl`. The `nodrix` entry point remains a compatibility alias in 2.x.

Always inspect the checked-out build for complete option details:

```bash
plyctl --help
plyctl COMMAND --help
```

## Workspace and context

| Command | Purpose |
|---|---|
| `plyctl workspace init [DIRECTORY] [--force]` | Create `nodrix.yaml` and conventional workspace directories. |
| `plyctl workspace show [--json]` | Show final workspace resolution. |
| `plyctl context list` | List contexts and mark the active one. |
| `plyctl context show` | Show the resolved active context. |
| `plyctl use NAME` | Persist the active context in `.nodrix/context`. |

## Environment

| Command | Purpose |
|---|---|
| `plyctl env show [--json]` | Show setup scripts and merged variables. |
| `plyctl env export` | Print shell exports for the resolved environment. |
| `plyctl env check` | Run declared preflight checks. |
| `plyctl prepare` | Resolve, check, and build the execution environment. |
| `plyctl shell` | Open an interactive shell with sources and variables loaded. |

## Execution and supervision

| Command | Purpose |
|---|---|
| `plyctl run [PIPELINE]` | Run in the foreground. |
| `plyctl up [PIPELINE] [--profile NAME] [--force]` | Start a supervised background run. |
| `plyctl down [--timeout SECONDS]` | Stop the supervised process group. |
| `plyctl restart [PIPELINE]` | Stop and start again. |
| `plyctl ps` | Show supervised process status. |
| `plyctl logs [-n N] [-f]` | Read or follow the runtime log. |
| `plyctl top` | Interactive runtime metrics using the selected view. |

## Graph inspection

| Command | Purpose |
|---|---|
| `plyctl validate [PIPELINE]` | Validate manifest, graph, ports, types, and providers. |
| `plyctl inspect [PIPELINE]` | Display graph and component details. |
| `plyctl plan [PIPELINE]` | Explain execution and memory planning. |
| `plyctl explain [PIPELINE]` | Explain resolved behavior and decisions. |
| `plyctl diagnose [PIPELINE]` | Run structured diagnostics. |
| `plyctl optimize [PIPELINE]` | Analyze optimization opportunities. |
| `plyctl benchmark ...` | Measure pipeline behavior using command-specific options. |

## Providers and catalog

The provider and catalog groups expose discovery, metadata, compatibility, trust, and diagnostics. Typical commands include:

```bash
plyctl provider list
plyctl provider info PROVIDER_ID
plyctl provider doctor PROVIDER_ID
plyctl catalog ...
```

Run `plyctl provider --help` and `plyctl catalog --help` because subcommands evolve with the Provider API.

## Data, device, recording, and media operations

The operation layer includes commands such as:

```bash
plyctl data doctor PATH
plyctl device doctor
plyctl device v4l2-probe
plyctl recording info PATH
plyctl recording repair PATH
plyctl media doctor
plyctl media probe INPUT
plyctl media select-encoder h264
plyctl media record ...
```

These commands are capability-dependent. A missing optional dependency should produce a clear diagnostic rather than being treated as a core runtime failure.

## System execution observation

`plyctl system run` renders the lifecycle and observation state of every
System and execution scope. Nested Systems are rendered as a tree. Each
child line preserves both its instance and resolved definition identities, for
example `lidar → livox-mid360` beneath `rpi5-mapping`.

Lifecycle and observation are separate:

- `state` describes execution progress: prepared, running, stopping, stopped,
  completed, or failed;
- `ready` is `yes`, `no`, or `unknown`;
- `health` is `healthy`, `degraded`, `unhealthy`, or `unknown`;
- `message` explains the most relevant failure, degradation, or uncertainty.

A health or readiness change is rendered even when the lifecycle state remains
`RUNNING`. If a backend does not expose observation, the CLI prints
`observation=unavailable`.

Observation is live execution state. It is not stored as a field in the System
YAML definition.

### JSON Lines execution events

Use `plyctl system run SYSTEM --output jsonl` for automation and external
monitoring. Standard output contains exactly one compact JSON object per line.
Human diagnostics and planner warnings are written to standard error.

Every event identifies itself with `apiVersion: nodrix.execution.event/v1` and
`kind: ExecutionEvent`. The stream uses `prepared`, `child_started`,
`dependency_waiting`, `dependency_satisfied`, `dependency_failed`, `started`,
`snapshot`, `stopping`, `finished`, and `error` events. Dependency events make
bounded readiness waits observable before the complete System reaches
`started`. Snapshot events are emitted only when presentation-relevant
lifecycle or observation data changes.

The `status` field contains the complete System hierarchy, including child
instance and resolved definition identities, execution scopes, readiness,
health, messages, and stable failure details. This public System stream is
separate from the legacy Pipeline runtime's internal `events.jsonl` journal.
