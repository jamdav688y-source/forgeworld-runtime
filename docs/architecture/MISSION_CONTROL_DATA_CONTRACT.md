# Mission Control — Read-Only Data Contract (DESIGN, not implemented)

Status: specification for a future read-only view (VIEW-1) and visual command environment. Nothing here is implemented, and no frontend exists.

## Rules every field obeys
1. **Derived, never stored.** Mission Control computes every field from existing records on read. It holds no state of its own and writes nothing: no record, ledger line, file or flag.
2. **Every value carries its provenance:** `{value, state, sources[], as_of}`.
   - `state` is one of `VERIFIED | OBSERVED | DERIVED | HYPOTHESIS | UNVERIFIED | UNKNOWN`.
   - `sources[]` holds record IDs, file paths with SHA-256, or `"operator-entry:<record id>"`.
3. **Absence is shown as absence.** A missing source yields `UNKNOWN`; an unprobed capability yields `UNVERIFIED` / `NOT_PROBED`. Nothing is estimated, defaulted, or extrapolated into telemetry.
4. **No actions.** The contract exposes no operation. Every button a future UI shows maps to an *existing* governed call that the operator invokes deliberately (review, sign, record delivery, and so on). The view never invokes one itself.
5. **Synthetic is always visible.** `synthetic: true` (from `-synthetic-` references) is shown on every row derived from synthetic records, and the totals of real and synthetic records are never mixed.

## Field sources

### A. Customer and engagement identity
| Field | Source | Verification state | Update mechanism | Authorization boundary |
|---|---|---|---|---|
| `customer_ref`, `project_ref` | `OUTCOME_SPEC` / `DELIVERY_PACKAGE` payloads | OBSERVED (operator-assigned strings; **not authenticated**) | new spec or package record | operator authors |
| `engagement_ref`, `account_ref` | `COMMERCIAL_SIGNAL` metadata | OBSERVED (pseudonyms) | operator records signals | operator |
| engagement ↔ customer binding | `OUTCOME_SPEC.engagement_ref` (ENGAGE-1; one customer per engagement, enforced) | DERIVED | spec record | operator authors spec |
| consent status | `OUTCOME_SPEC.consent_record_id` → `destination.consent_problems()` | DERIVED: `ACTIVE` / `WITHDRAWN_OR_VOIDED` / `NONE` | operator records consent or `REVERSAL` | operator; the consent document itself stays outside ForgeWorld |
| synthetic flag | refs and the `synthetic` payload field | DERIVED | — | — |

### B. Commercial pipeline state
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| business stage (OBSERVED … OUTCOME_MEASURED) | `commerce.engagement_state()` milestones plus delivery status; mapping in INTEGRATION_PLAN §5 | DERIVED | operator records commercial signals | operator only; sent ≠ accepted |
| hypotheses (price, savings) | `ESTIMATE_RECORDED` | HYPOTHESIS, always | operator | operator |
| contracted / invoiced amounts | `CONTRACT_SIGNED` / `INVOICE_ISSUED` | OBSERVED (document digest) | operator | operator |

### C. Evidence and provenance
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| initiating evidence | `origin.origin_brief().initiating_records` | OBSERVED (quoted / observed) | new observations | operator imports |
| independent origin count | `lineage.shared_origins()` | DERIVED | — | — |
| derived inputs | brief `derived_inputs` | DERIVED (never shown as evidence) | — | — |

### D. Seven-lens cognitive outputs
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| per-lens position and statement | `LENS_OUTPUT` records of the cycle | DERIVED (lens text is interpretation, never evidence) | a cycle admitted by R4 | R4 plus a human-started cycle |
| methodology notes vs open questions | `presentation.is_methodology_note()` split in the brief | DERIVED | — | — |
| caveat | lens questions are media-shaped (`ready_for_episode_planning`) | must be displayed as a known limitation | vocabulary change needs authorization | — |

### E. Contradictions and unresolved questions
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| contradiction list and status | `CONTRADICTION` records; `contradiction.assess()` | DERIVED (`OPEN` / `RESOLVED` / `CONFLICTING_VERIFICATION` / `VOID`) | new evidence, or verification under a policy | policy approved by a human |
| missing information | brief `uncertainty.missing_information` | OBSERVED (operator-entered) | operator | operator |

### F. Capability matching
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| matches (`matched_count / required_count`) | brief `capabilities.matches` (from `capabilities/registry.json`) | DERIVED | registry edit | — |
| reachability | always `NOT_PROBED` in this view | UNVERIFIED | — | the view never calls `router.route()` or `discover.probe_all()` |
| authorized to execute | always `false` | — | — | separate human authorization outside this view |
| promotion | `OutcomeDesk.promotion_candidate()` → gate unavailable (D1) | DERIVED | — | human promotion gate (not present) |

### G. Artifact versions and integrity
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| package versions and lineage | `DELIVERY_PACKAGE` (version, predecessor, `superseded_by`) | DERIVED | editor assembles a new version | editor |
| integrity | `DeliveryDesk.verify()`: `intact` and problems | VERIFIED (re-hashed on read) | — | — |
| criteria hash vs spec | report `outcome_spec.bound` / `problems` | DERIVED | — | — |

### H. Human approval requirements
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| review pending / done (reviewer ≠ editor) | `DELIVERY_EVENT` `REVIEW_*` | OBSERVED | reviewer records | human operator ID, **unauthenticated** |
| handoff signature pending / done (signer ≠ editor) | `HANDOFF_SIGNED` | OBSERVED | signer records | human operator ID |
| R4 decisions awaiting a human | cycle artifacts with `AWAITING_HUMAN_APPROVAL` | OBSERVED | governor ledger | human approval record |

### I. Delivery and acceptance
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| delivered | `DELIVERED` event | OBSERVED, **operator-asserted**; receipt never inferred | operator | operator |
| delivery acceptance (version-specific) | `CUSTOMER_*` event + quoted customer `OBSERVATION` | OBSERVED (customer-originated) | operator imports the customer's words | — |
| commercial acceptance | commerce `CUSTOMER_ACCEPTANCE` | OBSERVED (document digest) | operator | operator; independent of delivery acceptance |

### J. Payment and measured value
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| payment | `engagement_state().revenue` (only `VERIFIED_NET_RETAINED` counts) | VERIFIED only under a human-approved `PaymentPolicy`; otherwise `UNVERIFIED` | operator plus reconciliation `VERIFICATION_RESULT` | operator; no payment system access |
| measured value | `VALUE_MEASURED` (document digest) | OBSERVED | operator | operator |

### K. Phone/PC substrate status
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| device pairing, grants, reachability | `fabric/` (GrantStore, pairing, receiver-held grants) exists **only on unmerged Phase 1B** (`d1cba91`) | **UNKNOWN** on this branch | none until D1 | receiver-held grants; the view must never read keys or issue grants |
| last device heartbeat | no source on this branch | **UNKNOWN** | — | network listeners are not authorized |
| local capability probe state | `capabilities/discover.py` (opens sockets, runs subprocesses) | **UNVERIFIED**; not run by the view | operator-run probe, reported as a dated snapshot | operator |

### L. Agent and augmentation workflow state
| Field | Source | State | Update | Authorization |
|---|---|---|---|---|
| cognitive cycles (admitted / refused / awaiting human, depth, budget left) | governor ledger + cycle artifacts (`CycleRunner.load`) | OBSERVED | human-started cycles only | R4 |
| historical routing decisions | `router/decisions.jsonl`, `capabilities/history.jsonl` | OBSERVED, historical; never refreshed by the view | operator-run router | operator |
| running agents / sessions | no source in the repository | **UNKNOWN** | — | — |

## Response envelope (proposed)
```json
{"as_of": "<ISO-8601>", "source_commit": "<git sha>", "engagements": [{
  "customer_ref": {"value": "...", "state": "OBSERVED", "sources": ["cxp-rec-…"]},
  "synthetic": true,
  "stage": {"value": "DELIVERED", "state": "DERIVED", "sources": ["cxp-rec-…"]},
  "payment": {"value": null, "state": "UNKNOWN", "sources": []}
}], "substrate": {"pairing": {"value": null, "state": "UNKNOWN", "sources": [],
  "note": "fabric not on this branch (D1)"}}}
```
