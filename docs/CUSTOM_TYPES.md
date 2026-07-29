# Custom types

## Schema

```yaml
name: cobra.TrackedVehicle
version: 1
description: Vehicle state after tracking
fields:
  object_id: uint64
  class_id: uint16
  confidence: float32
  bbox: float32[4]
  velocity: float32[3]
  timestamp_ns: int64
```

Supported fixed-layout primitives:

```text
int8 uint8 int16 uint16 int32 uint32 int64 uint64 float32 float64
```

Fixed arrays use `type[count]`.

## Generate

```bash
nodrix type build types/tracked_vehicle.yaml -o generated_types
```

## Python

```python
from generated_types import TrackedVehicle

value = TrackedVehicle(
    object_id=10,
    class_id=2,
    confidence=0.93,
    bbox=(10.0, 20.0, 80.0, 120.0),
    velocity=(1.0, 0.0, 0.0),
    timestamp_ns=123456789,
)
```

Importing the module registers its type validator and network codec.

## C++

```cpp
#include "generated_types/cobra_trackedvehicle.hpp"

const auto* vehicle =
    reinterpret_cast<const nodrix::types::TrackedVehicle*>(message.payload.data());
```

The generated header contains a `static_assert` for the exact packed size.

## Pipeline contract

```python
class Producer(SourceNode):
    output_types = {"vehicle": "cobra.TrackedVehicle"}
```

```python
class Consumer(Node):
    input_types = {"vehicle": "cobra.TrackedVehicle"}
```

The same type name is used by Python nodes, C++ plugins, local validation, and
network streams.

## Complete example

See `examples/custom_type_native`.
