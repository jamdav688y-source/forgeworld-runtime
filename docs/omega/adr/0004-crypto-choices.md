# ADR-0004 — Cryptography: Ed25519, X25519, HKDF-SHA256, ChaCha20-Poly1305 via `cryptography`

**Status:** accepted · 2026-11-10

**Decision.** Use the `cryptography` package; implement no primitives here. Ed25519 for device
identity and signatures (deterministic, which makes receipts reproducible). Ephemeral X25519 +
HKDF per session (forward secrecy). ChaCha20-Poly1305 (fast on phones without AES hardware).
Static X25519 keys only for sealing offline bundles.

**Consequences.** `cryptography` is a **hard requirement** of every node: each event is signed at
append time, so without the package a node cannot be initialised or written to, and it fails
closed with `IdentityUnavailable`. Termux: `pkg install python-cryptography`; Windows:
`pip install cryptography`. Private keys are stored unencrypted, readable only by the owner (0600
on POSIX). They are protected by device security, not a passphrase (LIMITATIONS.md).
