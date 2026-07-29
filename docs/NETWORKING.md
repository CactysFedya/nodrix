# Nodrix networking

## No mandatory agent

A separate agent is not required.

On the publisher:

```bash
nodrix run
```

On another LAN device:

```bash
nodrix stream list
```

Every runtime with exported streams starts a small control-plane discovery
participant and a direct data-plane server. The stream data never travels
through discovery.

## Export a stream

```yaml
streams:
  exports:
    - name: /robot/camera/front
      from: camera.frame
      queue:
        capacity: 1
        policy: latest
```

Only explicit exports are visible on the network. Local internal edges remain
private and incur no networking overhead.

## Subscribe by name

```yaml
nodes:
  remote_camera:
    uses: core.stream_source
    parameters:
      name: /robot/camera/front

  consumer:
    uses: ./nodes/consumer.py:Consumer

edges:
  - from: remote_camera.output
    to: consumer.frame
```

## Explicit endpoint fallback

Some managed or isolated networks disable multicast. Use the endpoint reported
by the publisher or configure it directly:

```yaml
nodes:
  remote_camera:
    uses: core.stream_source
    parameters:
      uri: nodrix://192.168.1.50:7420/robot/camera/front
```

CLI:

```bash
nodrix stream echo nodrix://192.168.1.50:7420/robot/camera/front
```

## Multiple network interfaces

Nodrix enumerates active IPv4 interfaces and joins/sends discovery on each of
them. This matters when a laptop uses Wi-Fi for internet and wired Ethernet for
a robot network.

The payload connection is made to the source address from the received
advertisement, so the correct interface route is selected by the operating
system.

## Reliability and backpressure

Stream queues are independent of local edges.

```yaml
queue: {capacity: 1, policy: latest}
```

Recommended for preview, current state, detections, and telemetry where old
values are useless.

```yaml
queue: {capacity: 256, policy: block}
```

Recommended when every item must arrive and slowing the publisher is acceptable.

## What can be transmitted

Named streams are generic and can carry:

```text
Frame
Tensor
Detections
Tracks
PointCloud (future SDK or user type)
IMU/user telemetry
Audio
Events
Commands
Fixed-layout custom structures
Raw buffers
```

The core transport does not contain camera-specific assumptions.

## Performance design

Publishing to a stream does not serialize inside the producer thread. The
producer enqueues the message reference into a native bounded queue. A dedicated
worker performs encoding and fan-out.

For large payloads on Unix, `sendmsg` passes header, metadata, and payload
segments to the kernel as separate buffers. This avoids constructing another
large contiguous Python `bytes` object.

A physical network still requires data to enter the kernel/network stack. True
pointer zero-copy is possible only inside one address space or through future
shared/device-memory transports.

## Low-latency viewer subscribers

Version 0.6.0 lets each subscriber request its own queue policy. The viewer uses
`latest` with capacity `1`; a recorder can use a larger queue.

```bash
nodrix-viewer /robot/camera/front/preview
```

The recommended graph keeps raw frames local and exports an encoded branch:

```text
raw frame ──→ detector
         └──→ JPEG/H.264 encoder ──→ named stream ──→ viewer
```

A slow viewer has its own sender queue and cannot apply backpressure to the
local detector edge.
