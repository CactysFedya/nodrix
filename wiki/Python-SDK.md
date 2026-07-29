# Python SDK

Core:

```python
from nodrix import Message, Node, SourceNode, SinkNode
```

Vision:

```python
from nodrix.vision import Frame, Tensor, Detections, Tracks
```

`Node` является основным быстрым API. Синхронный `process()` вызывается напрямую
без asyncio на каждом сообщении.
