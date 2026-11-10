# ADR-0003 — Omega commercial ledger mirrors `cognition/commerce.py`, does not replace it

**Status:** accepted · 2026-11-10

**Context.** `cognition/commerce.py` is a verified CXP engagement state machine (a COMMERCIAL_SIGNAL
record type with human-approved PaymentPolicy). Omega events are signed, device-sequenced and
synced; CXP records are content-addressed and unsigned. Making one format carry the other
would weaken one of them.

**Decision.** `omega/commercial.py` keeps the same distinctions (claimed ≠ verified payment;
verbal ≠ written agreement; submitted ≠ accepted). Its vocabulary follows the directive's Stage G
list. It leaves `cognition/commerce.py` untouched.

**Consequences.** There are two commercial ledgers until an omega→CXP bridge exists (listed in
LIMITATIONS.md). The pocket node uses omega; the forge node can keep running the CXP pipeline.
