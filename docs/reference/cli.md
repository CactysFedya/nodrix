# Command-line reference

Run `plyctl --help` and `plyctl COMMAND --help` for the installed version's
authoritative options.

| Task | Command |
| --- | --- |
| Create a project | `plyctl init NAME --template core` |
| Validate YAML | `plyctl validate pipeline.yaml --strict` |
| Inspect the resolved graph | `plyctl inspect pipeline.yaml --resolved` |
| Run a pipeline | `plyctl run pipeline.yaml` |
| Production preflight | `plyctl validate pipeline.yaml --production` |
| Inspect providers | `plyctl provider list` |
| Diagnose runtime and providers | `plyctl doctor` |
| Generate editor schema | `plyctl schema` |
| Lock dependencies | `plyctl lock` |
| Inspect live metrics | `plyctl top` |

The legacy `nodrix` executable invokes the same command tree during the 2.x
compatibility window.
