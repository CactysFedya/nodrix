# CLI Reference

## Projects and execution

```bash
nodrix init PROJECT [--template TEMPLATE]
nodrix validate [pipeline.yaml] [--strict] [--json]
nodrix inspect [pipeline.yaml] [--memory|--live]
nodrix lock [pipeline.yaml] [--check]
nodrix run [pipeline.yaml] [--locked] [--metrics-listen HOST:PORT]
nodrix benchmark [pipeline.yaml]
```

## Health and artifacts

```bash
nodrix status
nodrix health [--watch]
nodrix metrics [--format json|prometheus]
nodrix runs list
nodrix runs show RUN
nodrix runs logs RUN
nodrix runs compare RUN_A RUN_B
```

## Packages and native plugins

```bash
nodrix package build DIRECTORY
nodrix package install PACKAGE.ndpkg
nodrix package list
nodrix package info NAME
nodrix package remove NAME
nodrix native build
nodrix native doctor
nodrix native inspect LIBRARY
```

## Streams and media

```bash
nodrix stream list
nodrix stream info NAME
nodrix stream echo NAME [--token TOKEN]
nodrix stream view NAME
nodrix-viewer SOURCE
nodrix media doctor
nodrix media probe SOURCE
nodrix media record SOURCE OUTPUT
nodrix media relay SOURCE OUTPUT
```

## Record/play and types

```bash
nodrix record STREAM... --output FILE.ndrx
nodrix play FILE.ndrx
nodrix recording info FILE.ndrx
nodrix type list
nodrix type info TYPE
nodrix type build SCHEMA.yaml
```
