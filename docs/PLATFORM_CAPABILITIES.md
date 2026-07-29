# Platform capability matrix

Nodrix probes runtime capabilities; this table describes supported packaging
and expected optional backends, not a promise that hardware exists.

| Platform | Core/native executor | Shared memory | Common optional backends |
|---|---|---|---|
| Linux x86-64 | yes | POSIX | CUDA, VAAPI, QSV, Vulkan |
| Linux ARM64 | yes | POSIX | V4L2 M2M, Vulkan |
| Raspberry Pi | yes | POSIX | V4L2 M2M, libcamera/FFmpeg |
| NVIDIA Jetson | yes | POSIX | CUDA, NVENC/NVDEC, NVMPI |
| Rockchip | yes | POSIX | MPP, RGA, Vulkan/NPU by plugin |
| macOS Apple Silicon | yes, universal2 wheel | local process APIs | Metal, VideoToolbox |
| Windows x86-64 | yes | Windows shared memory | CUDA, QSV, AMF |
| GPU servers | yes | local/remote edges | NVIDIA, Intel, AMD by installed stack |

CI compiles/tests Linux x86-64, Linux ARM64, macOS, and Windows. Hardware
backends are selected only after a real probe. `acceleration: required` fails
closed; `preferred` reports fallback; `disabled` makes the software choice
explicit.

Use:

```bash
nodrix device doctor
nodrix media doctor
nodrix inspect --memory
nodrix plan pipeline.yaml
```
