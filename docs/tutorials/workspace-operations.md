# Tutorial: workspace operations

This tutorial creates two execution contexts for the same pipeline: a local development context and a robot context.

## 1. Create the workspace

```bash
mkdir robot-stack
cd robot-stack
plyctl workspace init .
```

## 2. Define the project

Replace `nodrix.yaml` with:

```yaml
schema: nodrix.project/v1
name: robot-stack

defaults:
  pipeline: diagnostics
  context: local
  view: compact

pipelines:
  diagnostics: pipelines/diagnostics.yaml

contexts:
  local:
    environment: local
    profile: default
    view: compact

  robot:
    environment: ros2
    profile: mid360s
    view: operations
```

## 3. Create environments

`environments/local.yaml`:

```yaml
schema: nodrix.environment/v1
name: local
environment:
  LOG_LEVEL: debug
checks:
  - type: command
    command: python --version
```

`environments/ros2.yaml`:

```yaml
schema: nodrix.environment/v1
name: ros2
shell:
  source:
    - /opt/ros/jazzy/setup.bash
    - ${HOME}/livox_ws/install/setup.bash
environment:
  ROS_DISTRO: jazzy
  ROS_DOMAIN_ID: "26"
  ROS_AUTOMATIC_DISCOVERY_RANGE: SUBNET
checks:
  - type: file
    path: /opt/ros/jazzy/setup.bash
  - type: command
    command: ros2 --help
  - type: environment
    name: ROS_DISTRO
```

Variables may reference `${PROJECT_ROOT}`, `${HOME}`, and variables resolved earlier in the merge.

## 4. Create profiles

`profiles/default.yaml`:

```yaml
schema: nodrix.profile/v1
name: default
runtime_profile: realtime-balanced
variables:
  DEVICE_KIND: laptop
```

`profiles/mid360s.yaml`:

```yaml
schema: nodrix.profile/v1
name: mid360s
runtime_profile: realtime-low-latency
variables:
  DEVICE_KIND: robot
  LIDAR_MODEL: MID360S
  FASTLIO_CONFIG_FILE: ${PROJECT_ROOT}/configs/fastlio2/mid360.yaml
```

## 5. Inspect both contexts

```bash
plyctl context list
plyctl use local
plyctl workspace show
plyctl env check

plyctl use robot
plyctl workspace show
plyctl env show
plyctl env check
```

The local check should pass on any development machine. The robot check should fail clearly if ROS 2 or the Livox workspace is absent.

## 6. Enter the resolved shell

```bash
plyctl shell
```

The interactive shell loads setup scripts, resolved variables, and a prompt containing the workspace and context. Exit it normally with `exit`.

## 7. Launch and operate

```bash
plyctl prepare
plyctl up
plyctl ps
plyctl top
plyctl logs -f
```

Open another terminal for monitoring. Stop the pipeline:

```bash
plyctl down --timeout 10
```

`down` first sends `SIGINT`, then escalates to `SIGTERM` and `SIGKILL` only when the process group does not stop within the requested timeout.
