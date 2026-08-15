# Deploy the same project to another device

This guide describes the safe 2.3 workflow. The future `plyctl setup` and
`plyctl verify` commands are a product target, not a claim about the current
CLI.

## Choose the transfer unit

Prefer one of these, in order:

1. A Git commit plus exact source lock and project-local configuration.
2. A qualified wheelhouse built for the target OS and architecture.
3. A source archive with checksums for an offline target.

Do not copy `.venv`, `build/`, or platform-native wheels between macOS and
Linux ARM64.

## Source-based deployment

On the development machine:

```bash
git status --short
git commit -am "Prepare 2.3.0b1"
git push -u origin release/2.3.0b1-stabilization
```

On the target:

```bash
git fetch origin
git switch --track origin/release/2.3.0b1-stabilization

python3 -m venv ~/.venvs/plyctl-230b1
source ~/.venvs/plyctl-230b1/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install . --no-build-isolation
python -m pip install \
  ./packages/nodrix-spatial \
  ./packages/nodrix-mapping \
  ./packages/nodrix-ros2 \
  ./packages/nodrix-spatial-ros2
```

ROS 2 itself remains a system dependency and is not installed from PyPI.

## Offline wheelhouse

The wheelhouse must contain the `plyctl` wheel, every required provider wheel,
and all Python dependencies. Verify hashes before transfer.

```bash
python -m pip install \
  --no-index \
  --find-links ./wheelhouse \
  "plyctl==2.3.0b1"
```

A wheelhouse created on macOS is not a Linux ARM64 wheelhouse.

## Keep device-specific values local

Store IP addresses, RTSP credentials, ROS domain IDs, and device paths in
`local/` files excluded from Git. Commit templates and schemas, not secrets.

## Verify before replacing the working environment

```bash
plyctl --version
plyctl provider list
python -m pytest \
  tests/test_registry_file_module_cache.py \
  tests/test_release_metadata_consistency.py -q
```

For a robot integration, additionally verify ROS packages, topic types, rates,
frames, QoS, and clean shutdown.

## Rollback

Keep the previous virtual environment until qualification is complete.
Switching back should require only selecting the previous environment and
source commit; do not mutate the known-good environment in place.
