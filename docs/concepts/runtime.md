# Runtime and data plane

Plyctl separates graph control from message transport and supports Python, native nodes, provider-managed resources, and external applications.

## Graph elements

- **Node**: processing unit with declared input and output ports.
- **Edge**: connection between ports with queue and memory policy.
- **Message**: immutable envelope containing type, payload, sequence, timestamps, correlation data, and metadata.
- **Resource/session**: pipeline-scoped provider object shared by nodes or applications.
- **Managed application**: external process whose lifecycle and health are controlled by the runtime.

## Lifecycle

The compatibility lifecycle is:

```text
configure/open → start → process or produce → drain/flush → stop/close
```

The modern methods adapt to the existing `open`, `flush`, and `close` methods so providers written for earlier 2.x releases remain usable.

## Backpressure and freshness

Queue policy expresses semantics:

- `block`: lossless flow; producer waits when the queue is full;
- `drop_oldest`: bounded flow; oldest queued item is discarded;
- `latest`: freshness path; only the newest useful value is retained.

Choose policy by path, not globally. A pipeline can record losslessly while previewing with latest-frame semantics.

## Memory domains

The runtime can plan normal Python memory, managed buffers, shared memory, and native paths. Payloads are retained by reference inside `Message`; application code must not mutate a payload after emission unless the payload contract explicitly permits it.

## External middleware

Plyctl does not need to copy every external message into its Python graph. For ROS 2 integrations, large point clouds and IMU data can remain in DDS while Plyctl controls processes, health, logs, and operational metrics.
