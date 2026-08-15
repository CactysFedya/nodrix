# Examples

The repository examples are executable specifications. Prefer copying an example that matches the current branch over inventing a manifest from memory.

## Quickstart

`examples/quickstart/pipeline.yaml` demonstrates:

- `plyctl.dev`/compatibility manifest structure;
- builtin source, delay, console, and JSONL sink nodes;
- bounded queues;
- a minimal offline execution path.

Run from the repository root:

```bash
plyctl validate examples/quickstart/pipeline.yaml
plyctl inspect examples/quickstart/pipeline.yaml
plyctl run examples/quickstart/pipeline.yaml
```

## Provider API

The provider example demonstrates packaging, entry-point registration, provider metadata, node descriptors, installation, compatibility checks, and diagnostics.

## ROS 2 and FAST-LIO2

The integration examples demonstrate managed external applications, external DDS links, ROS environment setup, topic health probes, and operational views.

## Project templates

Create generated examples with:

```bash
plyctl init PROJECT --template core
plyctl init PROJECT --template vision
plyctl init PROJECT --template media
plyctl init PROJECT --template network
```

List actual templates and options with:

```bash
plyctl init --help
```
