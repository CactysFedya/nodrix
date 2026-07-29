# Nodrix Production Vision example

This is the reference host-memory pipeline for Nodrix 1.3.0:

```text
FFmpeg source -> letterbox -> NCNN YOLO -> ByteTrack -> overlay -> H.264 stream
```

Install:

```bash
python -m pip install -e ".[vision-ncnn,media,viewer]"
```

Place an exported NCNN model and labels in `models/`, or set:

```bash
export NODRIX_MODEL=/absolute/path/to/yolo26n_ncnn_model
export NODRIX_LABELS=/absolute/path/to/coco.names
export NODRIX_SOURCE=rtsp://camera/stream
```

Validate and run:

```bash
nodrix validate examples/vision_production/pipeline.yaml
nodrix inspect examples/vision_production/pipeline.yaml --resolved
nodrix run examples/vision_production/pipeline.yaml
```

Open the encoded preview from another machine:

```bash
nodrix-viewer nodrix://HOST:7420/vision/preview/h264
```

The 1.3.0 implementation intentionally uses BGR host memory between FFmpeg,
OpenCV and the NCNN Python binding. Copy/device-transfer accounting remains
visible; DMA-BUF, Vulkan and fully native inference are later optimization
stages, not claims of this reference pipeline.
