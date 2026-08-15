# Production operation checklist

## Pin and identify the release

- Pin `plyctl==2.3.0a1` or a specific repository commit.
- Keep the pipeline, workspace files, provider packages, and hardware configuration in version control.
- Record the output of `plyctl workspace show --json` with deployment artifacts.

## Validate before launch

```bash
plyctl env check
plyctl validate
plyctl inspect
plyctl plan
plyctl prepare
```

Do not use a successful import as a substitute for manifest validation.

## Separate path semantics

- Lossless recording paths: bounded queues with `block` and sufficient capacity.
- Real-time preview and control paths: small queues with `latest` or `drop_oldest` where data loss is explicitly acceptable.
- Keep large ROS 2 payloads in DDS when the pipeline only needs process management and health sampling.

## Secure providers and plugins

- Prefer metadata-first provider discovery.
- Enforce provider allowlists in controlled deployments.
- Verify signatures and trust-store entries when distributing provider artifacts.
- Use process isolation for untrusted or crash-prone native plugins.

## Operate predictably

```bash
plyctl up
plyctl ps
plyctl top
plyctl logs -f
plyctl down --timeout 15
```

Collect `.nodrix/logs/`, resolved workspace output, runtime metrics, and relevant ROS 2 diagnostics during incidents.

## Test failure modes

Before deployment, test:

- missing setup script;
- missing device or model file;
- provider import failure;
- child process crash and restart behavior;
- SIGINT shutdown;
- full recording queue;
- unavailable ROS 2 topic;
- host reboot with stale `.nodrix/supervisor.json`.
