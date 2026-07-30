# Nodrix roadmap: 2.0 to 3.0

Nodrix 2.0 fixes the stable universal runtime contracts. Releases 2.1–2.9 add
a provider/backend ecosystem without removing legacy behavior. Nodrix 3.0
removes the compatibility architecture only after the modular APIs and
migration tooling have been frozen.

## Compatibility rule for 2.x

Manifest v2, the Python Node API, Plugin C ABI 2, existing Node ids,
`nodrix.lock`, NDRX2, the native runner, existing pipelines, and CLI commands
remain supported throughout 2.x. Published tags are immutable; release fixes
use patch versions.

## Milestones

- **2.0 — Universal Runtime Core:** stable graph runtime, native/plugin data
  plane, recording, security, planning, lifecycle, and recovery.
- **2.1 — Provider API 1:** metadata-first discovery, detached signatures,
  trust/allowlist policy, feature negotiation, legacy adapter, and unified
  doctor.
- **2.2 — Backend API 1:** generic semantic and memory-domain contracts,
  capability inventory, safe/deep probe metadata, and removal of
  FFmpeg/NCNN names from Core planning.
- **2.3 — Hardware-aware Planner:** bounded end-to-end candidates, semantic
  constraints, deterministic ranking, benchmark evidence, and
  `execution.lock`.
- **2.4 — Domain packages:** independently versioned `nodrix-media`,
  `nodrix-vision`, `nodrix-ros2`, recording codecs, and compatibility package.
- **2.5 — Platform packs:** Raspberry Pi, Hailo beta, typed ROS 2 adapters, and
  native ROS 2 production dataplane.
- **2.6 — Functional qualification:** real Raspberry Pi 5/Hailo-8 and ROS 2
  Jazzy/Humble endurance, recovery, QoS, thermal, and workload evidence.
- **2.7 — Deployment compiler:** compile one graph into explicit host
  manifests, remote edges, ROS namespaces/remappings, and secret-free
  deployment locks without a central scheduler.
- **2.8 — Memory-path qualification:** compare planned and observed transfers,
  qualify real zero-copy paths, and fail strict production on lock violations.
- **2.9 — Ecosystem freeze:** freeze provider/backend/capability/lock/platform
  contracts and ship conformance plus non-destructive 3.0 migration tooling.
- **3.0 — Stable modular runtime:** remove built-in domain implementations,
  compatibility imports, deprecated aliases/fields, and the legacy registry.

The final runtime will safely discover providers and hardware, construct
semantically compatible end-to-end plans, measure permitted variants, explain
and lock the decision, then reproduce it locally, remotely, or through ROS 2.
It will not promise support for every NPU, universal zero-copy, hidden model
compilation, a central cluster scheduler, training, or automatic production
PKI.
