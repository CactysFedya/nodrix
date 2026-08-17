# Self-Describing YAML

Nodrix follows the rule:

> **Self-Describing, but never misleading.**

YAML files created for direct user editing may contain comments that explain
their role, relationships, commands, and optional fields.

Those comments belong only to the authoring layer. They are not part of the
canonical model.

## Two representations

A human-facing project scaffold may contain explanatory comments:

```yaml
# Nodrix System
#
# What:
#   A System is the canonical definition of the whole executable system.
#
apiVersion: nodrix.system/v1
kind: System
name: robot
```

Canonical serialization contains only canonical data:

```yaml
apiVersion: nodrix.system/v1
kind: System
name: robot
```

Both documents describe the same canonical System.

Comments do not affect:

- `EntityRef`
- `RevisionRef`
- Definition identity
- `SystemModel`
- Plan
- Execution
- provenance

## Authoring languages

The language used for generated comments is selected in `nodrix.yaml`:

```yaml
schema: nodrix.project/v1

defaults:
  view: compact
  language: en
```

Supported values are currently:

```text
en
ru
```

For example:

```bash
plyctl project init robot --language en
plyctl project init robot --language ru
```

Projects created before the language field existed default to English.

## Canonical vocabulary is not translated

The language setting changes comments only.

Canonical keys and type names remain stable:

```yaml
apiVersion: nodrix.system/v1
kind: System
name: robot
targets: []
resources: []
applications: []
```

A Russian scaffold therefore still uses `targets`, `resources`,
`applications`, `System`, `Profile`, `RuntimePreset`, `Definition`, and `Plan`.

This allows examples to move between English and Russian documentation without
schema conversion.

## Generated project resources

The self-describing standard currently applies to:

- `System`
- `Workflow`
- `Environment`
- `Profile`

### System

System is the canonical executable architecture.

Its scaffold may explain validation, planning, execution, inspection, targets,
resources, applications, graphs, and relations.

### Workflow

Workflow represents a finite engineering operation composed of steps.

Its scaffold may explain execution, Operation binding, dependencies, working
directories, conditions, cache, and other optional step fields.

### Environment

Environment describes host/process prerequisites such as shell setup files,
environment variables, platform constraints, and checks.

Environment does not describe the executable architecture.

### Profile

Profile is a named project configuration overlay.

It must remain distinct from RuntimePreset:

```text
Profile       = project configuration overlay
RuntimePreset = execution/performance defaults
Environment   = host/process prerequisites
```

Profile is not an executable Definition.

## Comment structure

Human-facing scaffolds should use a small set of predictable sections where
appropriate:

```text
What / Что это
Use it for / Используйте для
Relationship / Связь понятий
Commands / Команды
Optional fields / Необязательные поля
Start simple / С чего начать
```

Not every resource needs every section.

The goal is progressive disclosure, not embedding a complete manual into every
YAML file.

## Canonical rule

Generated comments may evolve without changing canonical identity.

Canonical serializers remain comment-free unless a caller explicitly requests
a human-facing authoring representation.
