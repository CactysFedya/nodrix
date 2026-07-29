# Nodrix 0.6.0 — Low-Latency Viewer and Media Streams

## Goal

Version 0.6.0 makes distributed visual pipelines usable without requiring a GUI
node inside the edge graph. A camera can feed a detector locally and export an
independent preview that a laptop opens or closes at any time.

## Implemented

### Standalone viewer

```bash
nodrix-viewer SOURCE
```

Supported sources:

- named Nodrix stream;
- explicit `nodrix://host:port/path` URI;
- local camera index;
- `/dev/video*` device;
- local video file;
- RTSP/HTTP source supported by OpenCV.

### Latest-frame rendering

- one-slot mailbox;
- non-blocking overwrite of stale undisplayed frames;
- subscriber queue `capacity=1`, `policy=latest`;
- continuously drained stream socket;
- small TCP receive buffer request;
- independent publisher queue per subscriber.

### Viewer telemetry

- receive and display FPS;
- sequence;
- resolution;
- overwritten frame counter;
- wall-clock latency estimate;
- fullscreen, scaling, screenshots;
- headless mode and JSON report.

### Encoded frame contract

Added:

```text
MediaCodec
EncodedFrame
vision.encoded_frame
```

The Nodrix wire layer transports the compressed buffer without creating an
additional combined Python payload before `sendmsg`.

### JPEG media nodes

```text
vision.jpeg_encoder
vision.jpeg_decoder
```

The updated vision template creates a raw local inference branch and a separate
compressed preview branch.

### Per-subscriber QoS

The subscribe handshake now carries the requested queue policy and capacity.
A viewer may request `latest:1` while another recorder subscribes with a larger
reliable queue.

## Examples

Publisher:

```bash
nodrix init camera-app --template vision
cd camera-app
nodrix run
```

Laptop:

```bash
nodrix stream list
nodrix-viewer /camera-app/preview --fps 30
```

Fallback without multicast:

```bash
nodrix-viewer nodrix://192.168.1.50:7420/camera-app/preview
```

## Verification

- 27 tests pass;
- native queue/buffer/plugin extensions pass;
- encoded-frame network round-trip passes;
- JPEG encode/decode passes;
- RGB and JPEG viewer conversion passes;
- latest-slot overwrite behavior passes;
- generated vision template contains the compressed preview graph;
- headless viewer processes a real local video.

## Known boundaries

- direct Nodrix H.264/H.265 access-unit decoding is not implemented;
- JPEG encoding creates a required compressed output buffer;
- the network receiver currently allocates a receive owner for every wire
  message;
- shared memory between separate processes is not included;
- cross-device latency depends on clock synchronization;
- graphical display requires an OpenCV build with GUI support.

The next media-focused step is a native FFmpeg/GStreamer package with H.264/H.265
hardware encoding and decoding, followed by shared-memory transport and
record/play.
