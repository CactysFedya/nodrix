# Примеры

Repository examples являются executable specification текущей ветки.

## Quickstart

```bash
plyctl validate examples/quickstart/pipeline.yaml
plyctl inspect examples/quickstart/pipeline.yaml
plyctl run examples/quickstart/pipeline.yaml
```

Он показывает builtin source, delay, console/JSONL sinks и bounded queues.

## Provider API

Provider example показывает packaging, entry point, metadata, descriptors, installation и diagnostics.

## ROS 2 и FAST-LIO2

Integration examples показывают managed applications, external DDS links, ROS environment, topic health и operations views.

## Project templates

```bash
plyctl init PROJECT --template core
plyctl init PROJECT --template vision
plyctl init PROJECT --template media
plyctl init PROJECT --template network
plyctl init --help
```
