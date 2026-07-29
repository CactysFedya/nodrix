# Distributed runtime

Nodrix exports only explicitly named streams. Discovery finds local-network
endpoints; direct `nodrix://` and verified `nodrix+tls://` URIs work without
discovery.

Remote edges retain bounded queues, reconnect budgets, transport metrics,
schema/version checks, message-size limits, tokens, IP allowlists, and optional
mutual TLS. A slow or disconnected subscriber cannot create an unbounded queue.

Placement metadata records the intended host:

```yaml
placement:
  default: local
  nodes:
    source: edge-camera
    detector: gpu-server
```

The current 2.0 runtime uses explicit stream source/sink adapters to cross
hosts; placement is a stable planning/deployment contract, not an invisible
central scheduler. See `NETWORKING.md` for discovery and transport details.
