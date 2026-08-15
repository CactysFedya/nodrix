# Workspaces and contexts

A pipeline manifest describes graph behavior. A workspace describes how that graph is selected and operated on a particular host.

## Separation of concerns

```text
nodrix.yaml                 project aliases and contexts
pipelines/*.yaml            graph definitions
environments/*.yaml         host setup, variables, checks
profiles/*.yaml             hardware and runtime tuning
views/*.yaml                operator-facing metric columns
.nodrix/                    active context, runs, logs, supervisor state
```

This avoids embedding machine-specific paths, ROS setup scripts, and operator preferences in reusable pipeline manifests.

## Resolution model

Plyctl searches upward for `nodrix.yaml`. It then resolves:

1. a pipeline argument, alias, or default pipeline;
2. the active context from `.nodrix/context` or project defaults;
3. the context's environment, profile, and view;
4. inline documents, explicit paths, or conventional files under their directories;
5. merged and expanded variables;
6. environment setup scripts and preflight checks.

A direct pipeline path remains valid without a workspace, which preserves simple one-file usage.

## Contexts are named operating modes

Examples:

- `local`: laptop environment, default profile, compact view;
- `robot`: ROS 2 setup, sensor profile, operations view;
- `simulation`: simulator environment, simulated-time variables, debug view.

A context should describe a coherent target, not a single temporary flag.
