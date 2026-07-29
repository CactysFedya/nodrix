# Unified Python/C++ video graph

Build the supplied C++ plugin and generate the input video:

```bash
nodrix native build
python examples/video_passthrough/generate_demo_video.py
nodrix run examples/unified_native/pipeline.yaml
```

Graph:

```text
Python/OpenCV video source → C++ frame plugin → Python/OpenCV writer
```

The C++ plugin receives the underlying frame buffer and returns a native buffer view without copying frame bytes.
