# Nodrix 1.5.0 — Multi-rate Vision and Hardware-first Runtime

Nodrix 1.5.0 combines the planned 1.4.2 CLI/TUI work with the first production
multi-rate Vision graph. A detector may process only the newest available frame
while a frame-clocked tracker predicts and publishes state at the source rate.

## Multi-rate tracking

The new built-in node is `vision.realtime_bytetrack`:

```text
source frames ───────────────────────────────▶ tracker.frame
      └─ latest → preprocess → detector ─────▶ tracker.detections
                                                   │
                                                   └─ tracks at frame clock
```

The node:

- uses `frame` as the `latest_available` trigger port;
- consumes each detector result at most once;
- predicts between detector measurements;
- stores bounded historical tracker states;
- applies delayed measurements to the matching historical frame;
- replays prediction to the current frame;
- preserves IDs across detector gaps;
- reports predicted, replayed and discarded measurement telemetry.

IoU association is implemented in a compiled C++20 extension using direct
Python buffer access. The Kalman state remains on the CPU because tracker data
is small and transferring it to a GPU would normally add more overhead than it
removes. The production block requires the native association backend; the
Python backend remains an explicit portability/debug option.

## Hardware-first, without hidden fallback

Media encoders support three policies:

- `required` — start only when a hardware encoder passes a runtime probe;
- `preferred` — probe hardware first, then report a visible software fallback;
- `disabled` — intentionally use software.

Generated Vision projects use `preferred` so they also run on platforms that do
not physically contain an H.264/H.265 encoder. A strict deployment can change
one block value to `required`. Startup output and runtime metrics always show the
selected backend and whether it is hardware or software.

The NCNN detector supports `backend: auto|cpu|vulkan` and
`acceleration: required|preferred|disabled`. `auto` chooses Vulkan when the
installed NCNN runtime exposes a usable GPU, otherwise it uses native CPU
inference (including platform SIMD used by NCNN).

FFmpeg hardware adapters cover VideoToolbox, V4L2 M2M, Rockchip MPP,
NVIDIA NVENC/NVMPI, Intel QSV/VAAPI and AMD AMF when the installed FFmpeg
build and device drivers expose them. Probes feed the same raw BGR path used
by the persistent runtime encoder, and backend-specific arguments are shared
between probe and execution. VideoToolbox explicitly disables internal
software fallback.

## CLI and TUI

- `nodrix inspect` renders a compact graph instead of parameter tables;
- `nodrix inspect --details` adds resolved block parameters;
- `nodrix inspect --node NAME` focuses one node instance;
- `nodrix node list --pipeline pipeline.yaml` shows only implementations used by
  one pipeline;
- `nodrix run` prints actual runtime lifecycle events (`READY`, `RUNNING`,
  `STOPPED`) rather than calling configured nodes ready prematurely;
- `nodrix top` is an htop-style single-screen view;
- stale-frame replacement, queue overflow and synchronization misses are
  reported separately;
- metrics can be configured in `pipeline.yaml`, so a normal project starts with
  `nodrix run` and no required CLI flags.

## Vision template

The generated graph uses a 30 FPS source clock, latest-frame detection,
frame-clocked tracking, bounded queues, exact-sequence overlay and a
hardware-first encoder policy. All implementation parameters stay in their
corresponding block YAML files.

## Discovery and Viewer

LAN discovery remains agent-free:

```bash
nodrix stream list
nodrix-viewer /pipeline/preview/h264 --overlay
```

Direct `nodrix://HOST:PORT/name` URIs remain supported. Normal publisher
shutdown is handled as end-of-stream, and exact encoded latency remains hidden
until H.264/H.265 chunks are represented as timestamped access units.

## Honest limitations

- The frame source and overlay currently use host BGR buffers. Full V4L2
  DMA-BUF capture, device-resident preprocessing and native libav nodes are not
  claimed in this release.
- Raspberry Pi 5 does not contain an H.264/H.265 encoder. On that platform an
  overlaid preview therefore requires visible software encoding unless an
  external accelerator or a client-side overlay architecture is used.
- The C++20 tracker accelerates association, but the Kalman implementation is
  still NumPy. Moving the remaining state update into native code is a measured
  optimization target, not a compatibility requirement.
- Multi-rate tracking can publish at source rate only when downstream overlay
  and encoding can sustain that rate. Nodrix reports downstream bottlenecks
  rather than presenting tracker rate as end-to-end output rate.

Nodrix 1.x Node API, manifests, blocks, message contracts, wire protocol,
Plugin ABI 1.0 and `.ndrx` format remain compatible.
