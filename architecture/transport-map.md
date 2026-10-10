# ForgeWorld Transport Map

See `gap-matrix.md` #16, #17 for classification. Corresponds to Section 11
of the mission brief (Phone↔PC continuity).

## What "transport" means in this codebase today

`fabric/interface.py::FabricTransport` — a two-method Protocol
(`deliver(destination_node_id, envelope) -> dict`,
`pull(node_id) -> list`). Three implementations exist, each a genuine
adapter, none of them the architecture:

| Adapter | File | Boundary crossed | Tested |
|---|---|---|---|
| `InMemoryFabricTransport` | `fabric/transports.py` | none (same process) | via 19 fabric-contract tests |
| `LoopbackClientTransport` | `fabric/loopback/transport.py` | real OS process boundary, `AF_UNIX`/`AF_PIPE` (same machine) | 17/17 |
| (same class, different `family`) | `fabric/tcp/pc_node_server.py` uses `LoopbackClientTransport` with `family="AF_INET"` — **zero new client code** | real TCP/IP socket (loopback-bound in this sandbox) | 12/12 |

The TCP proof deliberately reused the loopback proof's client class
unmodified — the strongest available evidence that "transport is an
adapter" is actually true in this codebase, not just asserted in a
docstring.

## What has NOT been proven

- **The physical phone↔PC hop, at the ForgeWorld application layer.** The
  operator physically demonstrated a raw TCP packet crossing Android
  (Termux, `nc`) → Windows and a reply crossing back — this proves network
  reachability only, below any ForgeWorld message format, authority check,
  or identity verification.
- **`fabric/tcp/` on real Windows at all.** Only exercised in this Linux
  sandbox over `127.0.0.1`. The `AF_PIPE` code path (used by
  `fabric/loopback/` on real Windows, not the TCP path, which uses
  `AF_INET` identically cross-platform) has never been exercised anywhere.
- **`fabric/tcp/` in the physical Windows checkout, because it isn't there
  yet.** `Test-Path .\fabric\tcp\pc_node_server.py` returned `False` there
  as of the last reconciliation mission. A reconciliation package (archive
  + SHA-256 manifest + guarded PowerShell script) was produced and
  delivered; completion is unconfirmed.
- **Anything connecting `forgeworld-mobile-research/` (the real phone-side
  capture app) to `fabric/`.** These are two fully independent
  implementations today. The mobile-research app has its own local SQLite
  database and its own prompt-package export; nothing in `fabric/` reads
  from it, and nothing in it constructs a `fabric.ArtifactEnvelope`.

## Synchronization/Reconciliation (Section 17 of this mission, distinct from device transport)

The Windows-checkout divergence investigation (prior mission) is the only
real precedent for "reconciling divergent state without destroying
anything." Its method: (1) prove local test health first, (2) confirm
structural path-disjointness between the transfer unit and protected dirty
paths, (3) transfer by content-addressed archive + manifest rather than by
git ancestry (because shared ancestry with the Windows checkout's reported
branch/HEAD could not be established — neither exists in this repository's
fetched `origin` history), (4) verify by hash before and after, (5) commit
only on the receiving end, only after verification. This is a manual
procedure today, run once, by hand. Nothing in the codebase automates any
step of it.

## Direct implication for Section 11's required physical proof chain

```
ANDROID EVENT → DURABLE PHONE QUEUE → PHYSICAL TRANSPORT → PC INGEST →
IDENTITY VERIFICATION → DEDUPLICATION → EVENT LEDGER →
MEMORY/STATE PROJECTION → RECEIPT → ACKNOWLEDGEMENT TO ANDROID
```

Mapped against what exists: PHYSICAL TRANSPORT (TCP) — proven in sandbox,
unproven on real devices. PC INGEST / IDENTITY VERIFICATION / RECEIPT —
proven (`process_remote_capability_request()`, `FabricReceipt`).
DEDUPLICATION — proven narrowly (`FabricArtifactIndex`, in-memory only).
DURABLE PHONE QUEUE — does not exist; `termux_phone_client.py` sends
immediately or fails, it does not queue for later delivery on offline
interruption, which Section 11 explicitly requires ("Offline interruption
should produce durable queues, not silent loss"). EVENT LEDGER / MEMORY
PROJECTION — no EventFabric or PermanentMemory exists yet to project into
(see the respective maps). This chain cannot be fully proven until those
gaps close, independent of the physical-device question.
