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
