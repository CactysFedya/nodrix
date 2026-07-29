# Nodrix 1.8.0

Nodrix 1.8.0 completes the secure remote-edge path while retaining the direct,
bounded publisher-to-subscriber data plane.

## Highlights

- `nodrix+tls://` with TLS 1.2 or TLS 1.3;
- optional mutual TLS and per-stream token/IP policies;
- certificate-verifying discovery and direct URI clients;
- bounded reconnect with capped exponential backoff;
- explicit TCP/TLS transport metrics and execution-plan metadata;
- strict production rejection of unencrypted LAN exports.

The plaintext `nodrix://` scheme remains available for loopback, isolated
development networks, and backward compatibility. It is not silently upgraded:
the selected transport is visible in discovery, runtime events, plans, and
metrics.
