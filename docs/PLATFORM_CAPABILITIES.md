# Platform capability matrix

This matrix separates a stable contract from a path actually exercised by Core
CI. “Plugin” means that the ABI can carry the domain, but Nodrix Core does not
ship a general hardware operator for it.

| Capability | Linux x86-64 | Linux ARM64 | macOS ARM64 | Windows x86-64 |
|---|---|---|---|---|
| Python 3.11–3.14 | CI | CI | CI | CI |
| Packaged native runner | CI | CI | CI | CI |
| External C ABI plugin/native | CI | CI | CI | CI |
| C11 ABI header / C++20 SDK | CI | CI | CI | CI |
| Host in-process zero-copy | CI | CI | CI | CI |
| Process shared memory | POSIX CI | POSIX CI | POSIX/local CI | Windows CI |
| DMA-BUF contract | plugin | plugin | unavailable | unavailable |
| CUDA/ROCm device handle | plugin | plugin/platform | unavailable | plugin |
| Vulkan/OpenCL device handle | plugin | plugin | plugin | plugin |
| Metal device handle | unavailable | unavailable | plugin | unavailable |
| DLPack handle contract | plugin | plugin | plugin | plugin |
| Generic ROS 2 adapter | optional | optional | limited | limited |
| Automatic multi-host scheduler | no | no | no | no |

“CI” means compiled and functionally exercised on the release platform.
Hardware plugins still require their own driver, device, lifetime, and
same-device integration tests. A successful capability probe is required;
finding a library on `PATH` is not enough.

The pure native runner validates exact port type and memory-domain
compatibility. Matching opaque device handles pass from C ABI producer to C ABI
consumer without conversion. It reports planned and observed copies, but it
does not silently import one accelerator API into another.

`acceleration: required` fails closed; `preferred` reports fallback;
`disabled` makes the software choice explicit.

Use:

```bash
nodrix device doctor
nodrix media doctor
nodrix inspect --memory
nodrix plan pipeline.yaml
```

Raspberry Pi 5, Jetson, and GPU-workstation benchmark specifications are
included. Their hardware results are release-lab qualifications, not results
inferred from hosted CI.
