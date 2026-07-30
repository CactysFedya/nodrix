# Security model

## Streams

Explicit exports can be open, token-protected and restricted by IP/CIDR. Tokens should be read from environment variables.

```yaml
access:
  mode: token
  token_env: NODRIX_STREAM_TOKEN
  allow_ips: ["192.168.1.0/24"]
```

## Parser limits

Nodrix limits handshake, metadata and full message sizes before allocation. Schema IDs and schema versions are checked before payload decoding.

## Secrets

Run artifacts redact keys named `token`, `password`, `secret`, `api_key`, `apikey` and `authorization` in both the source-manifest copy and the resolved manifest. Environment placeholders remain visible, while inline values and resolved secrets are replaced. `validate --strict` rejects inline stream tokens and requires `token_env`.

## Remote stream transport

Production LAN streams should combine encrypted `nodrix+tls` transport with
token authentication or mutual TLS and, where useful, an IP allowlist.
`nodrix validate --strict` rejects an unencrypted non-loopback stream transport.
TLS certificate verification cannot be disabled by a client flag.

Private keys and tokens must not be committed to a project. Certificate and key
paths may be relative to the pipeline manifest; access tokens should be supplied
through `token_env`. Client trust and mTLS credentials may be supplied through
`NODRIX_STREAM_CA`, `NODRIX_STREAM_CERT`, and `NODRIX_STREAM_KEY`.

## Plugins

`.ndpkg` archives are SHA-256 checked before extraction and may be signed with
Ed25519. `nodrix plugin verify --public-key ... --require-signature` verifies
publisher identity, and installation retains the verification record.
Verification rejects traversal, symlinks, portable-name collisions, untracked
or duplicate members, and archive resource abuse. Installation is staged,
atomic, and immutable. Production mode can require signed plugins.

Native plugins execute trusted machine code. Use process isolation for
components outside the deployment trust boundary. The local registry is
offline: no package is downloaded or executed as a side effect of search.
Direct native library paths are checked before `dlopen` in production: they
must be absolute, below `security.native_plugin_allowlist`, present, and not
world-writable. Lock/run artifacts retain the resolved path and file hash.

## Recordings

NDRX2 readers bound metadata, index, packet, file, chunk, record, and stream
counts. Each checkpoint is checksummed, its index must exactly cover the record
region, record headers are cross-checked, and a finalized file rejects trailing
or duplicate sections.

## Production gate

`nodrix run --production` requires Manifest v2, explicit health timeouts and
deployment-safe hardware choices. It rejects implicit memory copies, relative
model/engine paths, unprotected non-loopback streams and unverified plugins
when signed plugins are required.
