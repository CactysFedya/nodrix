# Debug a pipeline

Use the following order; it separates static errors from environment and runtime failures.

## 1. Confirm resolution

```bash
plyctl workspace show
plyctl context show
plyctl env show
```

Look for an unexpected pipeline alias, context, source script, profile, or view.

## 2. Run preflight checks

```bash
plyctl env check
plyctl prepare
```

A failed file or command check is an environment problem, not a graph problem.

## 3. Validate the graph

```bash
plyctl validate [PIPELINE]
plyctl inspect [PIPELINE]
plyctl plan [PIPELINE]
```

Common failures:

- wrong `apiVersion` or missing required Manifest API v2 sections;
- node reference not found;
- an edge names a missing port;
- incompatible declared port types;
- provider metadata is incompatible with the runtime;
- queue or memory policy is invalid.

## 4. Explain and diagnose

The operation command set includes diagnostic helpers such as:

```bash
plyctl explain [PIPELINE]
plyctl diagnose [PIPELINE]
plyctl device doctor
plyctl data doctor PATH
```

Check `plyctl <command> --help` for exact options in the current commit.

## 5. Run in the foreground

```bash
plyctl run [PIPELINE]
```

Foreground execution exposes the first exception directly. Move to `plyctl up` only after startup is stable.

## 6. Inspect background startup failure

If `up` reports that the pipeline exited during startup:

```bash
plyctl logs -n 300
cat .nodrix/supervisor.json
```

The log path is also recorded in supervisor state.
