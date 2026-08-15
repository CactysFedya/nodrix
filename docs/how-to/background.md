# Run a pipeline in the background

## Start

```bash
plyctl prepare
plyctl up [PIPELINE]
```

Use `--profile` to override the resolved runtime profile for this launch and `--force` only when intentionally replacing stale supervisor state.

## Check status

```bash
plyctl ps
plyctl top
```

The supervisor state is stored under `.nodrix/supervisor.json`. `ps` removes stale state when its recorded process is no longer alive.

## Read logs

```bash
plyctl logs -n 200
plyctl logs -f
```

Background stdout and stderr are combined in `.nodrix/logs/runtime.log`.

## Restart

```bash
plyctl restart [PIPELINE]
```

This performs a normal `down` followed by a forced `up` for the selected pipeline.

## Stop

```bash
plyctl down --timeout 10
```

Plyctl sends signals to the process group so managed descendants can shut down together. If a process ignores `SIGINT`, shutdown escalates after the timeout.
