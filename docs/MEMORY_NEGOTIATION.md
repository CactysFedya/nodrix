# Memory negotiation

## Port declarations

```python
class Node:
    input_memory = {
        "input": {
            "allowed": ["cuda", "cpu"],
            "preferred": "cuda",
            "access": "read",
            "contiguous": True,
        }
    }
```

Short forms are accepted:

```python
input_memory = {"input": "cuda"}
input_memory = {"input": ["shared", "cpu"]}
```

## Manifest overrides

```yaml
nodes:
  detector:
    memory:
      inputs:
        tensor:
          allowed: [cuda, cpu]
          preferred: cuda
```

## Edge policy

```yaml
edges:
  - from: preprocess.tensor
    to: detector.tensor
    memory:
      domain: auto
      allow_copy: true
```

Global strict mode:

```yaml
runtime:
  memory:
    forbid_implicit_copies: true
```

## Inspection

```bash
nodrix inspect --memory
```

The planner displays:

- source and target memory;
- selected domain;
- planned copies;
- host/device transfers;
- required adapter;
- whether the current runtime supports the path.

Unsupported device conversions stop validation instead of silently downloading to CPU.
