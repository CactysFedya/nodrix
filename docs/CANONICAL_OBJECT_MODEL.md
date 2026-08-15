# Nodrix Canonical Object Model v1

## Status

Introduced in Nodrix 2.9.

The Canonical Object Model defines the stable identity, execution-history,
data, artifact, and provenance vocabulary used across Nodrix.

Its purpose is not to replace specialized System, Workflow, runtime, or backend
models. It provides a common layer through which those models can be identified,
executed, recorded, related, persisted, and inspected.

The central principle is:

> One system. One identity. One model.

## Model

The Canonical Object Model consists of four groups:

```text
IDENTITIES
+
REFERENCES
+
RECORDS
+
RELATIONS
Domain models remain specialized.

Nodrix does not require System, Workflow, Dataset, Artifact, Run, Backend,
and other concepts to inherit from one universal base class.

Canonical vocabulary
Definition

A declarative description of something that exists or can be used.

Examples include:

System
Workflow
Dataset definition
Artifact declaration
user-defined Definitions
System

A Definition representing an entire executable software system.

A System may contain targets, resources, applications, graphs, links,
and declared outputs.

Instance

A concrete use of a Definition inside a System.

Examples include node, resource, and application instances.

EntityRef

The stable logical identity of an entity.

Example:

nodrix://system/project/mapping

Entity identity is semantic and is independent of the physical path of the
source file.

Moving a YAML file does not change the EntityRef.

RevisionRef

An immutable reference to a specific content revision of an entity.

Example:

nodrix://system/project/mapping@sha256:<digest>

Changing the content creates a new revision.

The logical EntityRef may remain the same.

RecordRef

A reference to a historical record.

Examples:

nodrix://record/plan/plan-001
nodrix://record/execution/execution-001
nodrix://record/run/run-001
Operation

An action requested against an entity.

Examples:

build
test
validate
run
profile
benchmark
diagnose
calibrate
export
package
cleanup

Operation kinds are extensible.

User and plugin-defined operations may use domain-qualified names such as:

mapping.reconstruct
robot.calibrate
dataset.prepare
model.train
mycompany.flash-firmware

An Operation contains:

kind
subject
subject_revision?
parameters

A revision may be resolved during planning if the Operation does not pin one.

Plan

A concretely resolved way to perform an Operation.

The canonical envelope is PlanRecord:

PlanRecord
├── plan_id
├── kind
├── operation
├── subject_revision
├── payload
└── metadata

The payload is intentionally domain-specific.

For example, a System operation may carry an existing SystemExecutionPlan.

A Plan is not a Backend.

The same Operation and revision may produce different Plans.

Executor

The mechanism that performs an Operation Plan.

Conceptually:

                    Operation
                        │
                        ▼
                       Plan
                        │
                        ▼
                     Executor
                     /       \
                    /         \
                   ▼           ▼
          WorkflowExecutor   SystemOrchestrator
                                  │
                                  ▼
                           ExecutionBackend(s)

ExecutionBackend remains a lower-level System runtime abstraction.

Build, test, and engineering workflows are not ExecutionBackends.

Execution

The actual execution of a Plan.

ExecutionRecord is the canonical immutable observation of an execution:

ExecutionRecord
├── execution_id
├── plan
├── executor
├── state
├── started_at
├── finished_at
└── details

Canonical states are:

created
prepared
running
stopping
stopped
completed
failed
cancelled

Live process handles and runtime objects are not stored inside ExecutionRecord.

Run

A durable historical record of one terminal Execution.

RunRecord
├── run_id
├── execution
├── summary
└── metadata

A Run is created only from a terminal ExecutionRecord.

RunRecord is immutable.

Dataset and Artifact relationships are not embedded directly in RunRecord.
They are represented through canonical Relations.

Dataset

An identifiable materialized input or derived data object.

A DatasetRecord follows:

logical identity
+
immutable content revision
+
physical location

Example:

entity:
  nodrix://dataset/project/livox-session


revision:
  nodrix://dataset/project/livox-session@sha256:<digest>


uri:
  datasets/livox/session.ndrx

Changing the physical URI does not change logical identity or content revision.

Changing the content creates a new RevisionRef.

Artifact

An identifiable materialized output or result.

ArtifactRecord follows the same identity law:

logical identity
+
immutable content revision
+
physical location

Example:

entity:
  nodrix://artifact/project/global-map


revision:
  nodrix://artifact/project/global-map@sha256:<digest>


uri:
  artifacts/maps/map.ply

The existing System v1 Artifact model is an expected-output declaration.

ArtifactRecord represents an actual materialized result.

Relation

A directed typed relationship between canonical references.

Examples:

Plan       --executed_as--> Execution
Execution  --recorded_as--> Run


Run        --consumes-----> Dataset revision
Run        --produces-----> Artifact revision


Revision   --derived_from-> Revision
Revision   --supersedes---> Revision

Structural relation kinds also include:

requires
provides
depends_on
placed_on

Relation kinds are extensible.

Examples:

robotics.calibrated_by
ml.trained_from
simulation.generated_from

Relations remain separate from records.

Provenance

Provenance is the relation graph that explains where data and results came
from and how executions are connected.

Example:

Plan
  │ executed_as
  ▼
Execution
  │ recorded_as
  ▼
Run
  ├── consumes ──► Dataset revision
  └── produces ──► Artifact revision

This allows history to grow without adding provenance-specific fields to every
canonical record.

Execution chain

The universal canonical execution chain is:

Operation
    ↓
Plan
    ↓
Execution
    ↓
Run

Specialized Nodrix subsystems may implement different planners and executors,
but canonical history uses the same model.

System runtime bridge

Nodrix 2.9 does not replace the existing System execution architecture.

The existing chain remains:

Definition
    ↓
Instance
    ↓
SystemModel
    ↓
SystemExecutionPlan
    ↓
SystemOrchestrator
    ↓
ExecutionBackend

The canonical bridge adds identity and history around that architecture:

SystemModel
    ↓
SystemExecutionPlan
    ↓
PlanRecord
    ↓
SystemOrchestrator
    ↓
ExecutionRecord
    ↓
RunRecord

This bridge is intentionally one-way and non-destructive.

Run document

Canonical Run history is persisted using:

nodrix.run/v1

Default local layout:

.nodrix/
└── runs/
    └── <run-id>/
        └── run.json

A Run document is historical evidence.

It is not a blind serialization of the live Python object graph.

In particular, domain-specific PlanRecord payloads are not required to be
serialized into the canonical Run document.

Persistence rules

Canonical Run documents are:

versioned
deterministic
atomically written
immutable once written
validated when loaded

Writing identical content for the same Run is idempotent.

Writing different content under the same Run identity is rejected.

Compatibility

Canonical run storage coexists with legacy Nodrix run storage.

Existing legacy precedence remains:

summary.json
run.json
status.json

The run index can expose both legacy and canonical history.

Legacy projects are not required to migrate immediately.

CLI

Canonical Runs are visible through:

plyctl runs list
plyctl runs show <run-id>

Machine-readable output remains available with:

--json

Nodrix CLI presentation is intentionally borderless.

Tables and help output should avoid box-drawing frames.

Non-goals of v1

Canonical Object Model v1 does not define:

nested System composition
System v2
a Dataset registry
an Artifact registry
a universal Workflow executor
automatic conversion of every legacy operation
a capability negotiation model

These can build on top of the canonical foundation.

Architectural laws
Identity law
logical identity
+
immutable revision
+
physical location

These concepts are distinct.

Execution law
Operation
→ Plan
→ Execution
→ Run
Provenance law

Relations are separate from records.

Compatibility law

Canonical models extend existing working runtime architecture rather than
requiring a rewrite.

Vocabulary law

One word has one architectural meaning.

Avoid using the same term for different lifecycle concepts.

Version boundary

Nodrix 2.9 establishes the Canonical Object Foundation.

Future releases may connect additional engineering operations such as build,
test, benchmark, profile, diagnostics, calibration, and export to the same:

Operation → Plan → Execution → Run

without changing the fundamental canonical vocabulary defined here.
