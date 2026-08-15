# Getting started

This section takes a new user from an empty machine to a validated and running Plyctl workspace.

## Learning path

1. [Install Plyctl 2.3.0a1](installation.md).
2. [Create and inspect a workspace](first-workspace.md).
3. [Run and modify a pipeline](first-pipeline.md).
4. Choose the next path in [Next steps](next-steps.md).

At the end you should understand:

- where `nodrix.yaml`, pipeline manifests, environments, profiles, and views live;
- how a context selects an environment, profile, and operational view;
- why `plyctl prepare` should run before `plyctl run` or `plyctl up`;
- how a node reference in YAML resolves to a builtin, provider node, or local Python class;
- where logs and supervisor state are stored.
