"""FORGEWORLD OMEGA (FW-SCS-001): offline-first dual-node evidence substrate.

Package layout (each module documents its own contract):

    canonical      deterministic serialization + domain-separated hashing
                   (reuses cognition.cxp.canonical_bytes)
    policy         closed vocabularies and the governance rules every event
                   must satisfy (who may assert what)
    identity       device keys (Ed25519 signing, X25519 key agreement),
                   pairing offers and short authentication strings
    events         the canonical, versioned, signed event model
    store          the append-only SQLite node store (events, artifacts,
                   FTS, receipts, conflicts, peers, device-local execution)
    receipts       deterministic, hash-chained evidence receipts
    reconcile      deterministic causal reconciliation + explicit conflicts
    relationship   contact memory, repetition / identity / privacy checks,
                   offline drafting
    commercial     commercial continuity (claimed vs verified payment...)
    tasks          durable task queue with local human authorization
    sync           mutually authenticated, encrypted store-and-forward sync
                   (live stream transport and sealed offline bundles)
    discovery      authenticated LAN peer discovery beacons
    forge          Windows / Ollama model routing, benchmarks, repo analysis
    agents         bounded specialist panel (advisory only)
    evolution      experiment records + promotion gate with rollback point
    diagnostics    exportable diagnostic / mission-control report
    cli            `python -m omega ...`

Nothing in this package grants execution authority to model output, and
nothing executes an externally consequential action without a human
authorization event created on the executing device.
"""

SCHEMA = "fw.omega.event/1"
PACKAGE_VERSION = "1.0.0"
