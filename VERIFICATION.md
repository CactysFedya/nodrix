# Nodrix 1.0.1 verification

## Scope

Nodrix 1.0.1 is a packaging and installation patch release. Runtime APIs, Plugin ABI 1.0, pipeline manifests, wire protocol, `.ndrx`, `.ndpkg` and lock-file formats are unchanged.

## Automated tests

```text
Python/unit/integration: 62 passed
C++ Release CTest:       1/1 passed
```

The Python suite includes the 59 Nodrix 1.0.0 regression tests plus three release-packaging checks for:

- version/build metadata;
- supported release matrix and Node.js 24 GitHub Actions;
- offline-installation assets.

## Package builds

Built locally:

```text
nodrix-1.0.1-cp313-cp313-linux_x86_64.whl
nodrix-1.0.1.tar.gz
```

Validated:

- wheel imports Nodrix 1.0.1;
- all four native modules load;
- source distribution builds a wheel with `--no-build-isolation --no-deps`;
- the source-built package loads all four native modules;
- release metadata is consistent across `pyproject.toml`, Python, CMake, project templates and `CITATION.cff`.

## Release workflow

The 1.0.1 workflow publishes:

- Linux x86-64 wheels;
- Linux ARM64 wheels;
- macOS Apple Silicon wheels;
- source distribution.

The failing macOS Intel job is excluded from this patch release. Official checkout, setup-python, upload-artifact and download-artifact actions use Node.js 24 based major versions. `cibuildwheel` is pinned to 3.4.1.

## Offline/source build fix

The build backend requirement is now:

```text
setuptools>=68
wheel
```

The project no longer requires SPDX license-expression parsing during metadata generation. This removes the Raspberry Pi failure caused by `setuptools>=77` calling unavailable `packaging.licenses` in an offline environment.
