# Nodrix Viewer

`nodrix-viewer` is a standalone low-latency display client. It is deliberately
separate from the processing graph: opening or closing a window on a laptop does
not restart the camera pipeline and cannot block the detector branch.

## Sources

```bash
nodrix-viewer /robot/front/preview
nodrix-viewer nodrix://192.168.1.50:7420/robot/front/preview
nodrix-viewer 0
nodrix-viewer /dev/video0
nodrix-viewer ./recording.mp4
nodrix-viewer rtsp://192.168.1.20/live
nodrix-viewer http://192.168.1.20/mjpeg
```

A source beginning with `/` is treated as a named Nodrix stream unless it is an
existing local path or a `/dev/video*` device.

## Commands

The same viewer is available through three entry points:

```bash
nodrix-viewer SOURCE
nodrix view SOURCE
nodrix stream view STREAM
```

The standalone executable is recommended for daily use because it is easy to
install on a laptop independently of a project.

## Options

```text
--fps N                 maximum display FPS; 0 uses the incoming rate
--overlay/--no-overlay  telemetry overlay
--fullscreen            fullscreen window
--scale X               display scale
--receive-buffer-kb N   TCP receive buffer request
--realtime-file         play files at recorded FPS
--fast-file             decode a local file as fast as possible
--headless               no window
--max-frames N          stop after N displayed frames
--json-stats            print machine-readable statistics
--screenshot-dir PATH   output for the S key
```

Keys:

```text
Q / Esc  close
S        screenshot
```

## Latency policy

For a Nodrix stream the viewer requests:

```text
queue capacity: 1
queue policy: latest
```

The socket is read continuously in a dedicated thread. The application mailbox
contains one message only. If another frame arrives before the GUI consumes the
previous one, the previous frame is overwritten.

This policy minimizes *avoidable* delay. It cannot remove physical capture,
encoding, network, decoding, compositor, and monitor latency.

## Overlay

The overlay displays:

- receive FPS;
- display FPS;
- resolution;
- message sequence;
- locally overwritten frames;
- estimated source-to-viewer latency;
- resolved stream URI or local source.

Latency uses the message wall-clock timestamp. The two devices should use NTP,
PTP, or another synchronized clock. Invalid clock differences are shown as
`n/a`.

## Supported Nodrix payloads

```text
vision.frame
vision.encoded_frame with JPEG, MJPEG, or PNG
```

Raw formats:

```text
BGR8
RGB8
GRAY8
BGRA8
RGBA8
```

Direct RTSP/H.264 URLs can be decoded by the OpenCV backend installed on the
laptop. Decoding H.264/H.265 access units transported as
`vision.encoded_frame` is intentionally deferred to the native media pack,
because it needs a persistent FFmpeg/GStreamer decoder rather than per-frame
OpenCV image decoding.

## Recommended edge graph

```text
Camera raw Frame
├── Detector / model / tracker
└── JPEG or H.264 encoder → exported preview → Nodrix Viewer
```

Do not compress the frame before local inference unless the model itself needs
encoded data. Keep the raw local branch zero-copy and compress only the network
preview branch.

## Headless verification

```bash
nodrix-viewer ./sample.mp4 \
  --headless \
  --max-frames 300 \
  --no-overlay \
  --json-stats
```

This is useful on CI, servers, and embedded boards where a windowing system is
not available.
