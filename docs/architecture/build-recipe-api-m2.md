# Build Recipe API M2

## Architecture

```text
nodrix.yaml#build
      │
      ▼
Build Recipe compiler
      │
      ▼
nodrix.workflow/v1
      │
      ▼
existing Workflow runner
      │
      ├── environment
      ├── conditions
      ├── logs
      ├── cache
      └── --rebuild
      │
      ▼
CMake / colcon / pip
```

Build recipes remain strictly outside the steady-state data path and outside `SystemModel` execution.

## Common recipe fields

```yaml
build:
  NAME:
    uses: cmake.release
    depends_on: [other]
    environment: {}
    setup: []
    when: {}
    timeout_seconds: 1200
    cache: auto
```

`cache` accepts `auto`, `true`, `false`, or an override mapping with `inputs`, `outputs`, and `environment`.

## CMake

```yaml
build:
  livox-sdk2:
    uses: cmake.release
    source: sources/Livox-SDK2
    build_dir: .nodrix/build/livox-sdk2
    install: true
    install_prefix: .nodrix/prefix/livox-sdk2
    configure_args:
      - -DBUILD_SHARED_LIBS=ON
    targets: []
    parallel: auto
```

## ROS 2 / colcon

```yaml
build:
  livox-driver:
    uses: ros2.colcon
    workspace: workspaces/livox_ws
    source_dir: src
    packages: [livox_ros_driver2]
    symlink_install: true
    depends_on: [livox-sdk2]
```

The selected project environment remains responsible for system/ROS underlays, e.g. `/opt/ros/jazzy/setup.bash`.

## Compatibility

When `nodrix.yaml#build` is empty or absent, `plyctl build` continues to resolve `workflows/build.yaml` exactly as before.

## Dependency environment propagation

`depends_on` is not only an ordering hint. Built-in recipes propagate the environment needed by their dependants:

- an installed CMake recipe contributes its project-local prefix to `CMAKE_PREFIX_PATH`;
- a ROS 2 colcon recipe contributes its generated `install/setup.bash` overlay.

Therefore a chain such as `Livox-SDK2 -> livox_ros_driver2 -> FAST-LIO2` can remain project-local without installing every dependency globally.
