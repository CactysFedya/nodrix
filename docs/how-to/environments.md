# Define environments, profiles, and contexts

## Put host setup in an environment

```yaml
schema: nodrix.environment/v1
name: ros2
shell:
  source:
    - /opt/ros/jazzy/setup.bash
    - ${HOME}/robot_ws/install/setup.bash
environment:
  ROS_DOMAIN_ID: "26"
  ROS_AUTOMATIC_DISCOVERY_RANGE: SUBNET
checks:
  - type: file
    path: /opt/ros/jazzy/setup.bash
  - type: directory
    path: ${HOME}/robot_ws/install
  - type: command
    command: ros2 --help
  - type: environment
    name: ROS_DISTRO
```

Supported preflight check kinds in 2.3 are `file`, `directory`, `command`, and `environment`.

## Put hardware and tuning values in a profile

```yaml
schema: nodrix.profile/v1
name: mid360s
runtime_profile: realtime-low-latency
variables:
  SENSOR_MODEL: MID360S
  CONFIG_ROOT: ${PROJECT_ROOT}/configs
  FASTLIO_CONFIG_FILE: ${CONFIG_ROOT}/fastlio2/mid360.yaml
```

## Combine them in a context

```yaml
contexts:
  robot:
    environment: ros2
    profile: mid360s
    view: operations
```

## Understand variable precedence

The workspace resolver merges:

1. environment variables declared by the environment document;
2. profile variables;
3. context variables.

Later layers override earlier ones. `${PROJECT_ROOT}` and `${HOME}` are available during expansion, and a variable may reference an earlier resolved variable.

## Export for another process

```bash
plyctl use robot
plyctl env export > /tmp/robot-env.sh
source /tmp/robot-env.sh
```

Prefer `plyctl shell` when working interactively because it also sources setup scripts in the correct order.
