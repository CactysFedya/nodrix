#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${REPO:-CactysFedya/nodrix}"
ASSIGNEE="${ASSIGNEE:-@me}"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

require gh
require python3

echo "Repository: $REPO"
gh auth status >/dev/null

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

retry_command() {
  local max_attempts="${RETRY_ATTEMPTS:-6}"
  local delay="${RETRY_DELAY_SECONDS:-2}"
  local attempt=1

  while true; do
    if "$@"; then
      return 0
    fi

    if (( attempt >= max_attempts )); then
      echo "ERROR: command failed after ${max_attempts} attempts: $*" >&2
      return 1
    fi

    echo "WARN: GitHub request failed (attempt ${attempt}/${max_attempts}); retrying in ${delay}s..." >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
    if (( delay > 20 )); then
      delay=20
    fi
  done
}

label_exists() {
  local name="$1"
  retry_command gh label list \
    --repo "$REPO" \
    --limit 500 \
    --json name \
  | python3 -c '
import json, sys
wanted = sys.argv[1]
raise SystemExit(0 if any(item.get("name") == wanted for item in json.load(sys.stdin)) else 1)
' "$name"
}

ensure_label() {
  local name="$1" color="$2" description="$3"

  if label_exists "$name"; then
    retry_command gh label edit "$name" \
      --repo "$REPO" \
      --color "$color" \
      --description "$description" >/dev/null
  else
    retry_command gh label create "$name" \
      --repo "$REPO" \
      --color "$color" \
      --description "$description" >/dev/null
  fi
}

milestone_exists() {
  local title="$1"
  retry_command gh api --paginate "repos/$REPO/milestones?state=all&per_page=100" \
  | python3 -c '
import json, sys
wanted = sys.argv[1]
items = json.load(sys.stdin)
raise SystemExit(0 if any(item.get("title") == wanted for item in items) else 1)
' "$title"
}

ensure_milestone() {
  local title="$1" description="$2"
  if milestone_exists "$title"; then
    echo "Milestone exists: $title"
    return 0
  fi

  retry_command gh api \
    --method POST \
    "repos/$REPO/milestones" \
    -f title="$title" \
    -f description="$description" >/dev/null
  echo "Created milestone: $title"
}

find_issue_by_title() {
  local title="$1"
  retry_command gh issue list \
    --repo "$REPO" \
    --state all \
    --limit 200 \
    --json number,title \
  | python3 -c '
import json, sys
wanted = sys.argv[1]
for issue in json.load(sys.stdin):
    if issue["title"] == wanted:
        print(issue["number"])
        break
' "$title"
}

create_or_get_issue() {
  local title="$1" body_file="$2" labels="$3" milestone="$4"
  local number url

  number="$(find_issue_by_title "$title")"
  if [[ -n "$number" ]]; then
    retry_command gh issue edit "$number" \
      --repo "$REPO" \
      --body-file "$body_file" \
      --add-label "$labels" \
      --milestone "$milestone" \
      --add-assignee "$ASSIGNEE" >/dev/null
    echo "Updated existing #$number: $title" >&2
    printf '%s\n' "$number"
    return 0
  fi

  url="$(retry_command gh issue create \
    --repo "$REPO" \
    --title "$title" \
    --body-file "$body_file" \
    --label "$labels" \
    --milestone "$milestone" \
    --assignee "$ASSIGNEE")"

  number="${url##*/}"
  echo "Created #$number: $title" >&2
  printf '%s\n' "$number"
}

best_effort_relation() {
  "$@" >/dev/null 2>&1 || true
}

echo "== Check GitHub API =="
retry_command gh api "repos/$REPO" --silent

echo "== Ensure milestones =="
ensure_milestone "2.4.0" "Universal provider, temporal, spatial, mapping and semantic contracts"
ensure_milestone "2.5.0" "ROS 2 qualification and the spatial-semantic mapping reference pipeline"

echo "== Ensure domain labels =="
ensure_label "area: spatial" "1D76DB" "Transport-neutral geometry, time, frames and calibration contracts"
ensure_label "area: mapping" "0E8A16" "Map contracts, persistence and map-building providers"
ensure_label "area: semantic" "5319E7" "Detections, tracks, observations and semantic/object maps"
ensure_label "area: integration" "FBCA04" "Reference pipelines and third-party application integrations"

cat > "$tmpdir/issue20.md" <<'EOF'
## Goal

Provide a small, stable SDK for independently installed providers without requiring changes in Core.

## Developer workflow

```bash
plyctl provider init my-provider
plyctl provider check
plyctl provider test
plyctl provider build
plyctl provider verify my-provider
```

## Scope

- typed provider metadata and capability declarations;
- lifecycle, configuration, endpoint and resource contracts;
- lazy discovery and loading;
- compatibility checks and lock-file identity;
- contract-test kit for source, sink, transform, stateful and external-application providers;
- scaffolds for Python, native and external-process providers;
- separately installed example providers, including one stateful mapping provider.

## Acceptance criteria

- [ ] provider scaffold is generated;
- [ ] public interfaces are typed, versioned and documented;
- [ ] contract tests detect incompatible providers;
- [ ] imports remain lazy until provider selection;
- [ ] providers declare whether payloads are copied, borrowed, shared or device-resident;
- [ ] stateful providers expose snapshot, restore and shutdown semantics;
- [ ] a separately installed example wheel passes CI;
- [ ] compatibility and deprecation policy is documented;
- [ ] Core contains no ROS 2, FAST-LIVO2, YOLO or map-format knowledge.
EOF

retry_command gh issue edit 20 --repo "$REPO" --body-file "$tmpdir/issue20.md" >/dev/null

cat > "$tmpdir/issue21.md" <<'EOF'
## Goal

Integrate MQTT tools, ROS 2 launch files, SLAM applications, FFmpeg, model servers and custom binaries without Core changes.

## Scope

- command, arguments, environment and working directory;
- declared typed endpoints and capabilities;
- readiness, liveness and health probes;
- restart/backoff policy;
- structured logs, metrics and run artifacts;
- graceful shutdown and complete process-tree cleanup;
- deterministic executable/configuration identity;
- resource limits and placement hints;
- explicit separation between control-plane orchestration and data-plane transport.

## Acceptance criteria

- [ ] provider can start and supervise a generic executable;
- [ ] process groups and child processes are terminated reliably;
- [ ] readiness never requires deserializing large payloads unless explicitly requested;
- [ ] exit code, signal, restart reason and effective command are stored in run artifacts;
- [ ] environment and configuration identity are reproducible;
- [ ] external applications can expose DDS/native endpoints without routing payloads through Python;
- [ ] tests cover normal exit, crash, timeout, restart and forced shutdown;
- [ ] FAST-LIVO2 can be represented as deployment configuration, not a Core special case.
EOF

retry_command gh issue edit 21 --repo "$REPO" --body-file "$tmpdir/issue21.md" >/dev/null

cat > "$tmpdir/issue25.md" <<'EOF'
## Goal

Provide reusable ROS 2 topic-health and rosbag record/replay operations for reproducible multi-sensor pipelines.

## Scope

- topic existence, type, publisher/subscriber count, frequency and freshness probes;
- timestamp age, inter-arrival jitter, dropped-sample and cross-topic skew metrics;
- reusable checks for LiDAR, IMU, camera, TF, odometry and registered point clouds;
- rosbag record, stop, inspect and replay operations;
- selectable topics, QoS overrides, storage backend and compression;
- run-artifact registration including command, topic set, metadata and bag location;
- deterministic replay profiles and optional simulated clock;
- optional strict data-readiness gates; graph/type readiness remains the default.

## Acceptance criteria

- [ ] probes work without deserializing PointCloud2/Image payloads in graph-only mode;
- [ ] frequency, freshness and skew thresholds are configurable;
- [ ] health output explains missing, stale, mismatched and slow topics separately;
- [ ] a bag containing LiDAR, IMU, camera and TF can reproduce an integration smoke test;
- [ ] record/replay lifecycle is managed and leaves no orphan process;
- [ ] bag metadata is linked to the Nodrix run artifact;
- [ ] strict payload-readiness is opt-in and bounded;
- [ ] Jazzy behavior and known QoS limitations are documented.
EOF

retry_command gh issue edit 25 --repo "$REPO" --body-file "$tmpdir/issue25.md" >/dev/null

cat > "$tmpdir/issue43.md" <<'EOF'
## Goal

Create repeatable performance baselines and CI regression budgets for the runtime, providers and representative high-throughput pipelines.

## Required benchmark groups

- queue latency, throughput, backpressure and drop policies;
- Python/native boundary and serialization cost;
- shared-memory and managed-buffer transfer;
- external-process startup, supervision and process isolation;
- stream framing and network transport;
- operations/telemetry overhead and planner cost;
- ROS 2 graph-only monitoring versus payload bridges;
- LiDAR + camera + pose multi-rate synchronization;
- incremental map tile/delta update throughput;
- object-observation fusion and persistence.

## Reference profiles

1. small in-process control graph;
2. external-process orchestration graph;
3. camera latest-frame detector graph;
4. LiDAR-camera mapping graph using PointCloud2/Image/Odometry metadata;
5. native spatial data path with explicit copy accounting.

## Metrics

- p50/p95/p99 latency;
- throughput and effective input/output rate;
- queue depth, drops and late samples;
- CPU, RSS and process-tree CPU/RSS;
- copied/borrowed/shared bytes and serialization count;
- startup/shutdown time;
- telemetry overhead;
- map update size and update rate.

## Acceptance criteria

- [ ] baselines are stored as versioned artifacts;
- [ ] CI has explicit warning/failure regression budgets;
- [ ] hardware-specific results are separated from simulated CI;
- [ ] every zero-copy or shared-memory claim has measured evidence;
- [ ] the spatial mapping profile fails when an accidental Python-list conversion is introduced;
- [ ] benchmark commands and environment identity are documented.
EOF

retry_command gh issue edit 43 \
  --repo "$REPO" \
  --body-file "$tmpdir/issue43.md" \
  --add-label "priority: high" >/dev/null
retry_command gh issue edit 43 --repo "$REPO" --remove-label "priority: normal" >/dev/null 2>&1 || true

cat > "$tmpdir/issue44.md" <<'EOF'
## Goal

Smoke-test every shipped project template, official integration and built distribution artifact.

## Acceptance criteria

- [ ] every project template generates and validates;
- [ ] every official integration is included in the intended artifact;
- [ ] tests run from built wheel/sdist, not only source checkout;
- [ ] modular wheels are tested independently and together;
- [ ] missing package data fails before publication;
- [ ] the FAST-LIVO2 integration validates in input and orchestrated modes;
- [ ] a bag-replay smoke fixture covers LiDAR, IMU, camera, TF, odometry and registered cloud metadata;
- [ ] headless mode is tested without RViz/DISPLAY;
- [ ] managed applications leave no orphan processes after success or failure;
- [ ] map and semantic integration fixtures validate their typed contracts without requiring robot hardware;
- [ ] hardware-only qualification is clearly separated from CI smoke coverage.
EOF

retry_command gh issue edit 44 --repo "$REPO" --body-file "$tmpdir/issue44.md" >/dev/null

cat > "$tmpdir/issue47.md" <<'EOF'
## Goal

Complete the remaining ROS 2 control-plane contracts after TF2/QoS are split into a dedicated blocking issue.

## Scope

- generic service client/server declarations;
- action client/server declarations;
- ROS lifecycle state mapping;
- composable-component container operations;
- parameter declaration and update operations;
- typed validation and run-artifact representation.

## Acceptance criteria

- [ ] generic contracts exist for services and actions;
- [ ] lifecycle components have explicit state mapping;
- [ ] component containers have explicit load/unload operations;
- [ ] parameter operations are typed and observable;
- [ ] no ROS-specific exception leaks into Core;
- [ ] Jazzy and Humble qualification scope is documented.

## Out of scope

TF2, QoS, namespace and remapping validation are tracked in the dedicated high-priority spatial ROS 2 issue created for the reference mapping pipeline.
EOF

retry_command gh issue edit 47 \
  --repo "$REPO" \
  --title "[ROS 2] Add services, actions, lifecycle and component-container contracts" \
  --body-file "$tmpdir/issue47.md" >/dev/null

echo "== Create new roadmap issues =="

cat > "$tmpdir/epic.md" <<'EOF'
## Goal

Deliver a reproducible reference pipeline that combines LiDAR, IMU and camera data, runs an externally managed visual-LiDAR-inertial odometry application and produces:

1. an incremental metric 3D map;
2. a 2.5D traversability map with a derived 2D navigation view;
3. a persistent semantic/object map from detector observations.

The implementation must prove Nodrix's domain-neutral architecture. FAST-LIVO2, YOLO, Livox and any concrete map backend remain replaceable providers/integrations and must not become Core concepts.

## Target dataflow

```text
LiDAR + IMU + Camera -> FAST-LIVO2 -> pose + registered cloud
registered cloud + pose -> incremental 3D map
3D map -> 2.5D elevation/traversability -> 2D cost/occupancy view
Camera -> detector -> 2D track
2D track + pose + calibration + LiDAR/map depth -> 3D observation -> object map
```

## Definition of done

- [ ] one command validates and starts the reference pipeline;
- [ ] live and rosbag-replay modes use the same logical graph;
- [ ] timestamps, clock domains, skew and late-sample policies are explicit;
- [ ] camera data can feed odometry and detection without mandatory duplicate decode/copy;
- [ ] PointCloud2/Image hot paths do not require Python object-list conversion;
- [ ] metric, traversability and object maps use incremental deltas/tiles rather than full-map copies;
- [ ] all external processes have health, metrics and complete cleanup;
- [ ] CPU, RSS, queue latency, drops and copy counts are measured;
- [ ] the exact FAST-LIVO2 ROS 2 implementation and license constraints are pinned;
- [ ] CI bag replay exists; hardware qualification remains a separate evidence gate;
- [ ] no FAST-LIVO2, YOLO, ROS 2 or sensor-specific behavior is added to Core.
EOF

epic="$(create_or_get_issue \
  "[Epic] Deliver the universal spatial-semantic mapping reference pipeline" \
  "$tmpdir/epic.md" \
  "area: integration,area: mapping,area: semantic,area: ros2,priority: high,type: epic,status: blocked,risk: performance" \
  "2.5.0")"

cat > "$tmpdir/time.md" <<'EOF'
## Goal

Define transport-neutral event-time and clock-domain contracts for correct multi-sensor and multi-rate processing.

## Scope

- source/event timestamp;
- receive/ingest timestamp;
- monotonic processing timestamp;
- clock-domain identity and provenance;
- known clock offset and uncertainty;
- sequence/correlation identity;
- timestamp validity and missing-timestamp policy;
- out-of-order, late and duplicate sample semantics;
- maximum age, skew and jitter metadata;
- optional simulated/replay clock mapping.

## Design constraints

- the contract is not ROS-specific;
- wall-clock time is never silently substituted for missing event time;
- timestamp conversion cannot lose source provenance;
- payload types may carry the contract without copying their large buffers;
- clock synchronization quality is observable.

## Acceptance criteria

- [ ] an ADR defines terminology and invariants;
- [ ] versioned timestamp/clock metadata is available to providers;
- [ ] validation rejects incompatible clock-domain use unless a mapping is declared;
- [ ] late/out-of-order behavior is explicit in the plan;
- [ ] run artifacts expose skew/jitter and clock-quality metrics;
- [ ] tests cover live, replay, simulated and malformed timestamps;
- [ ] ROS time, system time and hardware sensor time can be represented without Core depending on ROS.
EOF

time_issue="$(create_or_get_issue \
  "[Runtime] Define event-time, timestamp and clock-domain contracts" \
  "$tmpdir/time.md" \
  "area: core,area: runtime,area: spatial,priority: high,type: decision,status: needs-design,risk: compatibility" \
  "2.4.0")"

cat > "$tmpdir/join.md" <<'EOF'
## Goal

Add a bounded, observable temporal-join primitive for streams with different rates and arrival times.

## Required modes

- exact timestamp;
- nearest within tolerance;
- approximate/windowed;
- latest-before;
- interpolate when the contract supports it;
- fixed time window;
- watermark-driven completion.

## Required policies

- bounded per-input buffers;
- timeout and watermark;
- missing-input behavior;
- late and out-of-order handling;
- duplicate handling;
- overflow/drop policy;
- source timestamp preservation;
- deterministic replay behavior.

## Observability

- matched/unmatched counts;
- join latency;
- per-input buffer depth;
- late, expired and dropped samples;
- observed skew distribution.

## Acceptance criteria

- [ ] no mode can wait or buffer without an explicit bound;
- [ ] planning validates incompatible time/clock contracts;
- [ ] replay produces deterministic joins;
- [ ] joins preserve correlation and event-time provenance;
- [ ] tests cover camera + pose, LiDAR + pose and generic telemetry streams;
- [ ] large payload buffers are referenced, not copied, solely because of joining;
- [ ] the implementation remains domain-neutral and contains no ROS message_filters dependency.
EOF

join_issue="$(create_or_get_issue \
  "[Runtime] Add a bounded temporal join for multi-rate streams" \
  "$tmpdir/join.md" \
  "area: runtime,area: spatial,priority: high,type: feature,status: needs-design,risk: performance" \
  "2.4.0")"

cat > "$tmpdir/map.md" <<'EOF'
## Goal

Define backend-neutral contracts for stateful, incremental maps without sending or persisting the complete map on every update.

## Contracts

- `MapMetadata`;
- `MapRevision`;
- `MapTile` or chunk;
- `MapDelta`;
- `DirtyRegion`;
- `MapSnapshot`;
- `MapCheckpoint`;
- map-query capability metadata.

## Required metadata

- contract/version and backend identity;
- coordinate frame and timestamp;
- resolution and dimensionality;
- spatial bounds and tile/chunk key;
- map revision and parent revision;
- uncertainty/confidence;
- storage format and compression;
- memory/persistence policy;
- provenance of contributing observations.

## Initial map families

- sparse voxel/point map;
- elevation map;
- occupancy/cost grid;
- traversability layers;
- object/semantic map integration points.

## Acceptance criteria

- [ ] full snapshots and incremental deltas have separate typed contracts;
- [ ] consumers can detect missing/out-of-order revisions;
- [ ] backends can use CPU, shared-memory, file-backed or device-resident storage;
- [ ] map payloads do not depend on ROS, PCL, OctoMap, OpenVDB or a sensor type;
- [ ] snapshot/restore and bounded retention are defined;
- [ ] tests cover tile updates, revision gaps, checkpoint restore and concurrent readers;
- [ ] at least two toy backends prove implementation interchangeability;
- [ ] benchmarks record delta size, update rate, CPU and memory growth.
EOF

map_issue="$(create_or_get_issue \
  "[Mapping] Define incremental map tile, delta, revision and snapshot contracts" \
  "$tmpdir/map.md" \
  "area: mapping,area: spatial,area: memory,priority: high,type: feature,status: needs-design,risk: compatibility,risk: performance,risk: data-loss" \
  "2.4.0")"

cat > "$tmpdir/calibration.md" <<'EOF'
## Goal

Represent sensor calibration as a versioned deployment artifact and validate frame consistency before a spatial pipeline starts.

## Scope

- camera intrinsics, distortion model and image size;
- rigid extrinsics between sensors and body frames;
- IMU/LiDAR/camera frame conventions;
- optional temporal offset and uncertainty;
- sensor identity and compatible serial/device IDs;
- calibration source/tool, date, version and checksum;
- covariance or reported calibration error;
- conversion/import adapters, including FAST-Calib YAML where practical.

## Validation

- frame graph is connected for required transforms;
- transforms are finite and rotations are valid;
- image size/intrinsics are compatible;
- sensor identities match the deployment or require an explicit override;
- calibration artifact checksum is recorded in the run artifact;
- calibration and runtime clock-offset responsibilities are not conflated.

## Acceptance criteria

- [ ] a transport-neutral calibration schema and ADR exist;
- [ ] calibration artifacts are versioned and hashable;
- [ ] providers can import/export their native configuration without Core knowledge;
- [ ] invalid or disconnected frames fail at validation time;
- [ ] the effective calibration identity is visible in plan/status/run artifacts;
- [ ] tests cover valid, stale, mismatched and malformed calibration;
- [ ] FAST-LIVO2 deployment can consume a generated/provider-specific YAML derived from the canonical artifact.
EOF

calibration_issue="$(create_or_get_issue \
  "[Spatial] Add versioned calibration artifacts and frame validation" \
  "$tmpdir/calibration.md" \
  "area: spatial,area: manifest,priority: high,type: feature,status: needs-design,risk: compatibility" \
  "2.4.0")"

cat > "$tmpdir/semantic.md" <<'EOF'
## Goal

Define detector-neutral contracts that transform image detections into persistent 3D object observations and object-map updates.

## Contracts

- `Detection2D`;
- `Track2D`;
- `ObjectObservation3D`;
- `ObjectState`;
- `ObjectMapDelta`;
- class/label-set metadata;
- observation provenance and uncertainty.

## `ObjectObservation3D` minimum fields

- source/correlation ID and event timestamp;
- source camera/frame;
- class distribution and confidence;
- 3D point, centroid, extent or bounding volume;
- covariance/uncertainty;
- method used for depth/geometry association;
- pose/calibration/map revisions used for projection;
- optional 2D detection/track reference.

## Persistent object state

- stable object ID;
- first/last seen;
- observation count;
- fused class distribution;
- position/extent and uncertainty;
- static/dynamic/unknown classification;
- lifecycle/TTL and merge/split provenance.

## Acceptance criteria

- [ ] contracts do not depend on YOLO or a specific tracker;
- [ ] bbox and segmentation-mask observations are supported;
- [ ] 3D observation generation can use projected LiDAR points or a map/depth provider;
- [ ] the exact pose, calibration and map revision used are recorded;
- [ ] stale detections cannot silently use the latest pose;
- [ ] object-map updates are incremental and revisioned;
- [ ] tests cover association, missing depth, uncertainty, duplicate objects and replay determinism;
- [ ] a toy detector and toy object mapper prove provider interchangeability.
EOF

semantic_issue="$(create_or_get_issue \
  "[Semantic] Define 2D detections, 3D observations and persistent object-map contracts" \
  "$tmpdir/semantic.md" \
  "area: semantic,area: spatial,area: mapping,priority: high,type: feature,status: needs-design,risk: compatibility" \
  "2.4.0")"

cat > "$tmpdir/native.md" <<'EOF'
## Goal

Provide bounded high-throughput paths for image and point-cloud payloads while making every copy and serialization boundary observable.

## Scope

- managed/raw buffer views for image and point-cloud payloads;
- explicit ownership and lifetime semantics;
- borrowed, copied, shared-memory, file-backed and device-resident capability declarations;
- native/DDS bridge extension points;
- safe fallback compatibility bridges;
- copy/serialization byte counters and reasons;
- bounded queues and backpressure across native boundaries;
- ABI/version checks and clean shutdown.

## Constraints

- no conversion of complete PointCloud2/Image payloads to Python lists in the qualified hot path;
- orchestration may remain Python, but the high-rate data plane must not require Python object materialization;
- zero-copy is a measured capability, never inferred from configuration alone;
- providers must expose fallback behavior when a preferred memory path is unavailable.

## Acceptance criteria

- [ ] ownership/lifetime ADR is accepted;
- [ ] spatial bridge APIs preserve metadata while referencing large buffers;
- [ ] copy and serialization counts are exported to status/run artifacts;
- [ ] accidental materialization is detected by tests/benchmarks;
- [ ] fallback paths are bounded and clearly reported;
- [ ] at least one image and one point-cloud path are benchmarked;
- [ ] process shutdown releases shared/native resources without leaks;
- [ ] capability matrix distinguishes implemented, qualified and experimental memory paths.
EOF

native_issue="$(create_or_get_issue \
  "[Native] Add high-throughput spatial bridges and copy accounting" \
  "$tmpdir/native.md" \
  "area: native,area: memory,area: spatial,area: performance,priority: high,type: feature,status: needs-design,risk: performance" \
  "2.4.0")"

cat > "$tmpdir/tf_qos.md" <<'EOF'
## Goal

Add the ROS 2 spatial graph and transport declarations required for correct LiDAR-camera fusion and mapping.

## Scope

- declared static and dynamic TF2 frame relationships;
- transform lookup operation with event timestamp, timeout and interpolation policy;
- expected parent/child frame validation;
- namespace and topic remapping validation;
- publisher/subscriber QoS declarations and compatibility checks;
- observed-versus-declared TF/QoS inspection;
- run-artifact representation of effective frames, transforms and QoS.

## Acceptance criteria

- [ ] plan/validate represents required frames and transform direction;
- [ ] lookup is performed for the observation event time, not silently at latest time;
- [ ] missing, stale and disconnected transforms have distinct diagnostics;
- [ ] static and dynamic transforms are visually distinct;
- [ ] QoS incompatibility is detected before or during startup with a clear explanation;
- [ ] namespace/remapping is resolved into effective topic/frame identities;
- [ ] no TF2 or QoS concepts leak into Core;
- [ ] Jazzy and Humble qualification scope is documented;
- [ ] tests cover LiDAR, camera, IMU, body and map frame chains.
EOF

tf_issue="$(create_or_get_issue \
  "[ROS 2] Add TF2, event-time transform lookup and QoS validation" \
  "$tmpdir/tf_qos.md" \
  "area: ros2,area: spatial,area: manifest,priority: high,type: feature,status: needs-design,risk: compatibility" \
  "2.5.0")"

cat >> "$tmpdir/issue47.md" <<EOF

## Related work

TF2, event-time transform lookup, QoS, namespace and remapping validation are tracked by #$tf_issue.
EOF
retry_command gh issue edit 47 --repo "$REPO" --body-file "$tmpdir/issue47.md" >/dev/null

cat > "$tmpdir/fast_livo.md" <<'EOF'
## Goal

Pin and qualify one exact FAST-LIVO2 ROS 2 implementation for the official Nodrix reference integration.

## Why

The Nodrix integration intentionally treats FAST-LIVO2 as an external application, but the current deployment leaves the ROS 2 fork, commit, package, launch file and topic identities open. Upstream FAST-LIVO2 is a ROS 1/catkin project, so the ROS 2 deployment must be explicit and reproducible.

## Scope

- selected repository/fork and immutable commit SHA;
- patch set owned by Nodrix, if any;
- ROS 2 distribution, Ubuntu version, compiler and dependencies;
- package, executable, launch and parameter identities;
- exact input/output topics, message types, frames and QoS;
- supported LiDAR/camera/IMU profiles;
- calibration and synchronization requirements;
- build container or reproducible workspace manifest;
- reference rosbag and expected outputs;
- licensing and redistribution constraints;
- headless and RViz modes.

## Acceptance criteria

- [ ] deployment no longer relies on an unspecified FAST-LIVO2 ROS 2 variant;
- [ ] repository and commit SHA are recorded in lock/run artifacts;
- [ ] clean Ubuntu 24.04 + ROS 2 Jazzy build instructions pass;
- [ ] input/output topic and frame contracts validate statically;
- [ ] reference bag produces odometry and registered cloud outputs;
- [ ] shutdown leaves no orphan process;
- [ ] CPU/RSS and input/output rates are captured;
- [ ] calibration/synchronization assumptions are documented and validated;
- [ ] GPLv2 and any alternative-license implications are documented;
- [ ] the integration can be replaced by another odometry provider without changing Core or map contracts.
EOF

fast_issue="$(create_or_get_issue \
  "[Integration] Pin and qualify an exact FAST-LIVO2 ROS 2 implementation" \
  "$tmpdir/fast_livo.md" \
  "area: integration,area: ros2,area: performance,priority: high,type: research,status: needs-evidence,risk: compatibility,risk: performance" \
  "2.5.0")"

cat > "$tmpdir/metric_map_provider.md" <<'EOF'
## Goal

Implement one replaceable reference provider that consumes registered spatial observations plus pose and maintains an incremental metric 3D map.

## Initial backend requirements

- sparse voxel or chunked point representation;
- bounded local/active working set;
- configurable voxel resolution and spatial extent;
- incremental tile/delta output;
- snapshot/checkpoint and restore;
- map revision and dirty-region reporting;
- deterministic bag-replay mode;
- optional persistence without blocking the hot path.

## Provider boundaries

- input and output use `plyctl-spatial` and `plyctl-mapping` contracts;
- no Livox, FAST-LIVO2, ROS message or navigation knowledge in the provider core;
- a ROS 2 adapter may translate declared topics outside the provider;
- backend can later be replaced by OctoMap, Voxblox, OpenVDB or another implementation.

## Acceptance criteria

- [ ] registered cloud + event-time pose update the map without full-map copying;
- [ ] map deltas carry revision, frame, timestamp and bounds;
- [ ] memory growth is bounded by explicit policy;
- [ ] snapshot/restore reproduces the same map revision;
- [ ] dropped/late observations are counted and reported;
- [ ] tests cover empty input, motion, repeated observations and revision gaps;
- [ ] a synthetic and rosbag benchmark report update rate, CPU, RSS and delta size;
- [ ] the qualified path avoids Python-list point materialization.
EOF

metric_map_issue="$(create_or_get_issue \
  "[Mapping] Implement a reference incremental metric 3D map provider" \
  "$tmpdir/metric_map_provider.md" \
  "area: mapping,area: spatial,area: provider,area: performance,priority: high,type: feature,status: blocked,risk: performance,risk: data-loss" \
  "2.5.0")"

cat > "$tmpdir/traversability_provider.md" <<'EOF'
## Goal

Implement a replaceable provider that derives a 2.5D elevation/traversability map and a 2D navigation projection from the metric 3D map or registered spatial observations.

## Required 2.5D layers

- elevation/ground estimate;
- minimum and maximum observed height;
- slope;
- roughness;
- step/ledge estimate;
- obstacle probability;
- confidence/observation count;
- traversability cost and unknown state.

## 2D output

- occupancy or cost representation derived from the 2.5D layers;
- configurable robot footprint, clearance and height thresholds;
- stable frame, resolution, origin and revision metadata;
- incremental dirty-region updates.

## Acceptance criteria

- [ ] 2.5D is the source representation; 2D is a derived view;
- [ ] thresholds and robot geometry are deployment configuration, not Core behavior;
- [ ] input may be map tiles/deltas or bounded registered observations;
- [ ] updates are incremental and revisioned;
- [ ] unknown, free, obstacle and non-traversable states are distinguishable;
- [ ] synthetic ramps, steps, holes and obstacles have deterministic tests;
- [ ] provider can export a ROS-compatible grid through an adapter without depending on ROS internally;
- [ ] benchmark reports update latency, CPU, RSS and affected-cell count.
EOF

traversability_issue="$(create_or_get_issue \
  "[Mapping] Implement 2.5D traversability and 2D navigation projection providers" \
  "$tmpdir/traversability_provider.md" \
  "area: mapping,area: spatial,area: provider,area: performance,priority: high,type: feature,status: blocked,risk: performance" \
  "2.5.0")"

cat > "$tmpdir/vision_provider.md" <<'EOF'
## Goal

Add a detector/tracker provider interface and one YOLO-based reference implementation without making YOLO a Core or semantic-contract dependency.

## Scope

- image/frame input preserving event timestamp and calibration/frame references;
- detector output using the generic `Detection2D` contract;
- optional tracker output using `Track2D`;
- configurable latest-frame, queue and drop policies;
- model identity, label set, preprocessing and inference metadata;
- backend capability declaration for NCNN, ONNX Runtime, TensorRT or external process;
- structured latency, throughput and drop metrics.

## Performance behavior

- odometry and detector branches may consume one camera source without mandatory duplicate decode;
- detector delay never rewrites the original frame timestamp;
- latest-frame mode is available for slower detectors;
- image buffers are borrowed/shared when the backend supports it and copy counts are observable.

## Acceptance criteria

- [ ] provider API is model-family neutral;
- [ ] one YOLO reference backend produces versioned generic detections;
- [ ] an optional lightweight tracker preserves source timestamps;
- [ ] model/config/checksum identity is stored in run artifacts;
- [ ] queue depth, dropped frames, preprocess/inference/postprocess latency and FPS are reported;
- [ ] tests use a tiny deterministic fixture and do not require downloading a model at runtime;
- [ ] detector can be replaced by another provider without changing object-map fusion;
- [ ] qualified edge-device profile documents its backend and memory path.
EOF

vision_issue="$(create_or_get_issue \
  "[Vision] Add detector and tracker providers with a YOLO reference backend" \
  "$tmpdir/vision_provider.md" \
  "area: semantic,area: provider,area: integration,area: performance,priority: high,type: feature,status: blocked,risk: performance" \
  "2.5.0")"

cat > "$tmpdir/object_fusion_provider.md" <<'EOF'
## Goal

Implement a provider that converts timestamped 2D detections/tracks into 3D object observations and maintains an incremental persistent object map.

## Inputs

- `Detection2D` or `Track2D`;
- event-time camera pose/transform;
- calibration artifact;
- projected LiDAR points, depth provider or metric-map query;
- optional class and motion policies.

## Processing

- event-time temporal join;
- project spatial observations into the image or query geometry by ray/region;
- robust depth/cluster selection inside bbox or mask;
- transform observation into map frame;
- estimate centroid/extent and uncertainty;
- associate observations to persistent object IDs;
- classify static/dynamic/unknown and apply lifecycle/TTL policies.

## Acceptance criteria

- [ ] latest pose is never substituted for the required event-time pose without an explicit policy;
- [ ] missing depth and missing transforms produce bounded, observable outcomes;
- [ ] bbox and segmentation-mask paths are supported;
- [ ] each 3D observation records pose, calibration and map revisions used;
- [ ] persistent object updates are incremental and revisioned;
- [ ] duplicate, merge, split, stale and moving-object cases have tests;
- [ ] rosbag replay is deterministic for fixed configuration;
- [ ] metrics include association latency, rejected observations and map growth.
EOF

object_fusion_issue="$(create_or_get_issue \
  "[Semantic] Implement 2D-to-3D observation fusion and a persistent object-map provider" \
  "$tmpdir/object_fusion_provider.md" \
  "area: semantic,area: spatial,area: mapping,area: provider,priority: high,type: feature,status: blocked,risk: performance,risk: data-loss" \
  "2.5.0")"

cat > "$tmpdir/reference_pipeline.md" <<'EOF'
## Goal

Compose the qualified providers into one documented integration with reproducible rosbag replay and live-sensor modes.

## Required modes

- `input.yaml`: consume an already running sensor/odometry graph;
- `orchestrated-headless.yaml`: start managed applications without RViz;
- `orchestrated-rviz.yaml`: start visualization explicitly;
- `replay.yaml`: start rosbag playback using the same logical graph;
- optional detector-disabled and map-layer-disabled profiles.

## Required pipeline outputs

- odometry/pose and registered point cloud;
- incremental metric 3D map;
- 2.5D elevation/traversability map;
- derived 2D navigation grid/cost view;
- 2D detections/tracks;
- 3D object observations;
- persistent object-map deltas/snapshots.

## Acceptance criteria

- [ ] one command validates and starts each mode;
- [ ] exact external repositories, commits, model and calibration identities are locked;
- [ ] graph/type readiness is default; strict data readiness is explicit and bounded;
- [ ] camera feeds odometry and detection without mandatory duplicate source/decode;
- [ ] health covers sensor rate/freshness/skew, transforms and all managed applications;
- [ ] run artifacts register bags, maps, checkpoints, logs and configuration hashes;
- [ ] headless shutdown leaves no process or shared-memory leak;
- [ ] CI smoke replay succeeds from built artifacts;
- [ ] hardware qualification records CPU, RSS, rates, queue latency, drops and copy counts;
- [ ] integration documentation explains how to replace FAST-LIVO2, detector and map backends.
EOF

pipeline_issue="$(create_or_get_issue \
  "[Integration] Add reproducible bag-replay and live spatial-semantic mapping pipelines" \
  "$tmpdir/reference_pipeline.md" \
  "area: integration,area: ros2,area: mapping,area: semantic,priority: high,type: feature,status: blocked,risk: performance,risk: data-loss" \
  "2.5.0")"

# Add issue relationships where the current GitHub CLI/repository supports sub-issues and dependencies.
best_effort_relation gh issue edit "$join_issue" --repo "$REPO" --add-blocked-by "$time_issue"
best_effort_relation gh issue edit "$map_issue" --repo "$REPO" --add-blocked-by "$time_issue"
best_effort_relation gh issue edit "$semantic_issue" --repo "$REPO" --add-blocked-by "$time_issue"
best_effort_relation gh issue edit "$semantic_issue" --repo "$REPO" --add-blocked-by "$join_issue"
best_effort_relation gh issue edit "$tf_issue" --repo "$REPO" --add-blocked-by "$time_issue"
best_effort_relation gh issue edit "$fast_issue" --repo "$REPO" --add-blocked-by 21
best_effort_relation gh issue edit "$fast_issue" --repo "$REPO" --add-blocked-by 25
best_effort_relation gh issue edit "$fast_issue" --repo "$REPO" --add-blocked-by "$tf_issue"
best_effort_relation gh issue edit "$metric_map_issue" --repo "$REPO" --add-blocked-by "$map_issue"
best_effort_relation gh issue edit "$metric_map_issue" --repo "$REPO" --add-blocked-by "$native_issue"
best_effort_relation gh issue edit "$traversability_issue" --repo "$REPO" --add-blocked-by "$metric_map_issue"
best_effort_relation gh issue edit "$vision_issue" --repo "$REPO" --add-blocked-by 20
best_effort_relation gh issue edit "$vision_issue" --repo "$REPO" --add-blocked-by "$semantic_issue"
best_effort_relation gh issue edit "$vision_issue" --repo "$REPO" --add-blocked-by "$native_issue"
best_effort_relation gh issue edit "$object_fusion_issue" --repo "$REPO" --add-blocked-by "$semantic_issue"
best_effort_relation gh issue edit "$object_fusion_issue" --repo "$REPO" --add-blocked-by "$join_issue"
best_effort_relation gh issue edit "$object_fusion_issue" --repo "$REPO" --add-blocked-by "$calibration_issue"
best_effort_relation gh issue edit "$object_fusion_issue" --repo "$REPO" --add-blocked-by "$metric_map_issue"
best_effort_relation gh issue edit "$object_fusion_issue" --repo "$REPO" --add-blocked-by "$vision_issue"
best_effort_relation gh issue edit "$pipeline_issue" --repo "$REPO" --add-blocked-by "$fast_issue"
best_effort_relation gh issue edit "$pipeline_issue" --repo "$REPO" --add-blocked-by "$traversability_issue"
best_effort_relation gh issue edit "$pipeline_issue" --repo "$REPO" --add-blocked-by "$object_fusion_issue"
best_effort_relation gh issue edit "$pipeline_issue" --repo "$REPO" --add-blocked-by 25
best_effort_relation gh issue edit "$pipeline_issue" --repo "$REPO" --add-blocked-by 44
best_effort_relation retry_command gh issue edit "$epic" --repo "$REPO" --add-sub-issue "$time_issue,$join_issue,$map_issue,$calibration_issue,$semantic_issue,$native_issue,$tf_issue,$fast_issue,$metric_map_issue,$traversability_issue,$vision_issue,$object_fusion_issue,$pipeline_issue"

cat > "$tmpdir/epic-final.md" <<EOF
## Goal

Deliver a reproducible reference pipeline that combines LiDAR, IMU and camera data, runs an externally managed visual-LiDAR-inertial odometry application and produces:

1. an incremental metric 3D map;
2. a 2.5D traversability map with a derived 2D navigation view;
3. a persistent semantic/object map from detector observations.

The implementation must prove Nodrix's domain-neutral architecture. FAST-LIVO2, YOLO, Livox and any concrete map backend remain replaceable providers/integrations and must not become Core concepts.

## Target dataflow

\`\`\`text
LiDAR + IMU + Camera -> FAST-LIVO2 -> pose + registered cloud
registered cloud + pose -> incremental 3D map
3D map -> 2.5D elevation/traversability -> 2D cost/occupancy view
Camera -> detector -> 2D track
2D track + pose + calibration + LiDAR/map depth -> 3D observation -> object map
\`\`\`

## Existing blocking work

- [ ] #18 process-tree metrics and cleanup
- [ ] #20 Provider SDK and contract test kit
- [ ] #21 external-process provider adapter
- [ ] #24 DDS topic edges in plan/validate/inspect
- [ ] #25 topic health and rosbag operations
- [ ] #43 performance baselines and regression budgets
- [ ] #44 integration and artifact smoke tests
- [ ] #45 capability support matrix

## New blocking work

- [ ] #$time_issue event-time and clock-domain contracts
- [ ] #$join_issue bounded temporal join
- [ ] #$map_issue incremental map contracts
- [ ] #$calibration_issue calibration artifact and frame validation
- [ ] #$semantic_issue semantic/object-map contracts
- [ ] #$native_issue high-throughput spatial bridges and copy accounting
- [ ] #$tf_issue TF2 event-time lookup and QoS validation
- [ ] #$fast_issue pinned FAST-LIVO2 ROS 2 deployment
- [ ] #$metric_map_issue reference incremental metric 3D map provider
- [ ] #$traversability_issue 2.5D traversability and 2D navigation projection
- [ ] #$vision_issue detector/tracker provider and YOLO backend
- [ ] #$object_fusion_issue 2D-to-3D fusion and persistent object-map provider
- [ ] #$pipeline_issue reproducible bag/live integration

## Deferred ROS 2 control-plane work

- [ ] #47 services, actions, lifecycle and component-container contracts

## Definition of done

- [ ] one command validates and starts the reference pipeline;
- [ ] live and rosbag-replay modes use the same logical graph;
- [ ] timestamps, clock domains, skew and late-sample policies are explicit;
- [ ] camera data can feed odometry and detection without mandatory duplicate decode/copy;
- [ ] PointCloud2/Image hot paths do not require Python object-list conversion;
- [ ] metric, traversability and object maps use incremental deltas/tiles rather than full-map copies;
- [ ] all external processes have health, metrics and complete cleanup;
- [ ] CPU, RSS, queue latency, drops and copy counts are measured;
- [ ] the exact FAST-LIVO2 ROS 2 implementation and license constraints are pinned;
- [ ] CI bag replay exists; hardware qualification remains a separate evidence gate;
- [ ] no FAST-LIVO2, YOLO, ROS 2 or sensor-specific behavior is added to Core.
EOF

retry_command gh issue edit "$epic" --repo "$REPO" --body-file "$tmpdir/epic-final.md" >/dev/null

# Existing blockers linked to the epic when sub-issues are supported.
best_effort_relation retry_command gh issue edit "$epic" --repo "$REPO" --add-sub-issue "18,20,21,24,25,43,44,45"

cat <<EOF

Done.

Epic: #$epic
New issues:
  #$time_issue  Event-time and clock domains
  #$join_issue  Temporal join
  #$map_issue  Incremental maps
  #$calibration_issue  Calibration artifacts
  #$semantic_issue  Semantic/object maps
  #$native_issue  Native spatial data paths
  #$tf_issue  TF2 and QoS
  #$fast_issue  FAST-LIVO2 ROS 2 qualification
  #$metric_map_issue  Metric 3D map provider
  #$traversability_issue  2.5D traversability provider
  #$vision_issue  Detector/tracker and YOLO provider
  #$object_fusion_issue  2D-to-3D object fusion
  #$pipeline_issue  Bag/live reference pipeline

Updated existing issues: #20, #21, #25, #43, #44, #47
Review:
  gh issue view $epic --repo $REPO --web
  gh issue list --repo $REPO --milestone 2.4.0 --state open
  gh issue list --repo $REPO --milestone 2.5.0 --state open
EOF
