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

## Encrypted transport and mutual TLS

Use TLS for every non-loopback production export. Certificate paths are
resolved relative to the pipeline manifest:

```yaml
streams:
  bind_host: 0.0.0.0
  tls:
    enabled: true
    certificate: secrets/server.crt
    private_key: secrets/server.key
    minimum_version: TLSv1.2
  exports:
    - name: /robot/events
      from: source.output
      access:
        mode: token
        token_env: NODRIX_STREAM_TOKEN
```

Discovery advertises such endpoints as
`nodrix+tls://HOST:PORT/robot/events`. Clients verify the system trust store by
default. For a private CA:

```bash
nodrix stream echo \
  nodrix+tls://robot.local:7420/robot/events \
  --ca secrets/ca.crt
```

For mutual TLS add `client_ca` and `require_client_certificate: true` on the
server, then use `--cert` and `--key` on the client. Non-interactive consumers
can use `NODRIX_STREAM_CA`, `NODRIX_STREAM_CERT`, and `NODRIX_STREAM_KEY`.
There is deliberately no option to disable certificate verification.

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

Remote sources can use a finite reconnect budget:

```yaml
parameters:
  uri: nodrix+tls://robot.local:7420/robot/events
  ca_file: secrets/ca.crt
  reconnect_attempts_per_disconnect: 5
  reconnect_max_total_attempts: 20
  reconnect_window_seconds: 300
  reconnect_reset_after_stable_seconds: 60
  reconnect_backoff: 0.25
  reconnect_max_backoff: 4.0
  reconnect_jitter: 0.2
```

The per-disconnect limit bounds one recovery series. The rolling lifetime
budget prevents a server that repeatedly disconnects from resetting its retry
allowance forever. Stable operation resets the rolling budget. Backoff is
exponential, capped, jittered, and interruptible by shutdown.

Connection state is one of `connected`, `reconnecting`, `degraded`,
`budget_exhausted`, `failed`, or `closed`. Reports expose
`reconnect_attempts_total`, `reconnect_success_total`,
`reconnect_failures_total`, `reconnect_budget_remaining`, and
`connection_uptime_seconds`. The legacy `reconnect_attempts` parameter remains
accepted as the default for both new attempt limits.

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
