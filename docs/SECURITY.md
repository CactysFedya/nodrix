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

Native plugins execute trusted machine code. Use process isolation for untrusted Python/native components. Nodrix 1.0 has no remote-code installation or marketplace.
