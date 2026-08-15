# Nodrix 2.7 M1 — Project/System + Build/Workflow UX

This milestone keeps the existing architecture and joins the two lines that
already exist in 2.6:

```text
Project / Workflow                 System / Execution
      |                                  |
 prepare/build/test                validate/plan/run
      |                                  |
      +------------ Project -------------+
```

## User workflow

Create one project and register its default System:

```bash
plyctl project init robot
cd robot
plyctl project add system robot --default
plyctl project add environment pi --template raspberry-pi5 --default
plyctl project add workflow prepare
plyctl project add workflow build
plyctl project add workflow test
```

After that the normal path is deliberately short:

```bash
plyctl prepare
plyctl build
plyctl test
plyctl system validate
plyctl system plan
plyctl system run
```

The System path no longer has to be repeated when a default System is
registered. If `components/*.py` exist in the project, System commands resolve
the local typing-first SDK automatically.

## Fast build cache

Workflow v1 remains compatible. A step can opt into a fast local cache:

```yaml
schema: nodrix.workflow/v1
name: build

steps:
  - id: livox-sdk2
    cwd: sources/Livox-SDK2
    run: |
      cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
      cmake --build build --parallel
      cmake --install build
    cache:
      inputs:
        - sources/Livox-SDK2
      outputs:
        - sources/Livox-SDK2/build
      environment:
        - CC
        - CXX
        - CMAKE_BUILD_TYPE
```

On the first run the step is `SUCCEEDED`. If inputs are unchanged and declared
outputs still exist, the next run reports `CACHED` and does not start CMake at
all.

Force a real rebuild when needed:

```bash
plyctl build --rebuild
# or for an advanced/custom workflow
plyctl workflow run build --rebuild
```

The cache uses cheap file metadata and is intentionally a *local acceleration
cache*. It is not a release lock and does not replace stronger reproducibility
fingerprints/locks.

## Design rule

`system run` never clones sources, installs packages, or compiles C++.
Preparation/build changes the environment; System execution consumes the
prepared result.
