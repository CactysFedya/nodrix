# Hardware acceleration

Nodrix uses an explicit three-state policy:

- `required`: a compatible probed hardware backend is mandatory;
- `preferred`: hardware is tried first and every software fallback is reported;
- `disabled`: software execution is intentional.

Backend selection considers availability, format compatibility, memory-domain
transfers, and measured capability. A binary existing on `PATH` is not treated
as proof that its encoder or accelerator works.

`nodrix media doctor`, `nodrix device doctor`, `nodrix plan`, and
`nodrix inspect --memory` expose selected and rejected alternatives. Production
mode rejects `preferred`, because a deployment must choose whether fallback is
allowed before it starts.

Large payloads should stay in `dma_buf`, CUDA, Vulkan, Metal, shared, or another
declared domain. Required transfers are reported; implicit transfers can be
forbidden with `runtime.memory.forbid_implicit_copies`.
