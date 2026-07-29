# Custom Types

```yaml
name: robot.Telemetry
version: 1
fields:
  sequence: uint64
  temperature: float32
  position: float32[3]
```

```bash
nodrix type build telemetry.yaml -o generated_types
```

Генерируются Python-класс, C++ struct, бинарный codec и schema manifest.
