# Data Plane

Nodrix selects transport by placement:

```text
same process       -> reference + bounded queue
different process  -> shared-memory descriptor
different computer -> typed network stream
```

For descriptor-only process transfer, allocate the payload at the source:

```python
from nodrix import SharedBufferPool

pool = SharedBufferPool(block_size=2_764_800, capacity=8)
buffer = pool.acquire(2_764_800)
```

A normal NumPy or heap buffer stays zero-copy in-process but needs one staging
copy when moved to an isolated process. Copy counters are visible with:

```bash
nodrix inspect --live
```

Create a working example:

```bash
nodrix init data_demo --template data-plane
cd data_demo
nodrix inspect --live
```
