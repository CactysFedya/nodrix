# Progressive projects and finite workflows

A Nodrix project no longer needs to create its complete future architecture on
day one. The progressive project command writes only `nodrix.yaml` and local
Git ignore rules:

```bash
plyctl project init robot-stack
cd robot-stack
```

Add resources when the system actually needs them:

```bash
plyctl project add pipeline mapping --default
plyctl project add environment raspberry-pi5 --template raspberry-pi5
plyctl project add workflow prepare --template python-install
plyctl project add workflow build --template cmake-build
plyctl project add workflow test --template python-test
```

The resulting structure grows progressively:

```text
robot-stack/
├── nodrix.yaml
├── pipelines/
│   └── mapping.yaml
├── environments/
│   └── raspberry-pi5.yaml
└── workflows/
    ├── prepare.yaml
    ├── build.yaml
    └── test.yaml
```

Finite workflows use `schema: nodrix.workflow/v1` and execute steps in order:

```yaml
schema: nodrix.workflow/v1
name: build
steps:
  - id: configure-and-build
    run: |
      cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
      cmake --build build --parallel
```

Each workflow execution keeps per-step diagnostic logs under
`.nodrix/operations/<timestamp>-<workflow>/logs/`.

Canonical execution history is stored separately as immutable
`nodrix.run/v1` evidence under `.nodrix/runs/<run-id>/run.json`.

```bash
plyctl prepare --environment raspberry-pi5
plyctl build --environment raspberry-pi5
plyctl test --environment raspberry-pi5
```

Workflow steps support `cwd`, `environment`, `timeout_seconds`,
`continue_on_error`, and `when` conditions (`system`, `architecture`,
`command_exists`, `file_exists`, and `environment`). Working directories are
restricted to the project root.
