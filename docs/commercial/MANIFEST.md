# Commercial Readiness Package — Manifest

**Mission:** FW-ODCC1-COMMERCIAL-READINESS-001, preserved by FW-COMMERCIAL-ARTIFACT-PRESERVATION-001.
**Based on:** commit `0ef2ce3` (ODCC-1: outcome specifications bound to delivery packages).

**Status of every document: DRAFT, for human review.**
- No document has been sent to anyone.
- No document has had legal review.
- No customer, testimonial, agreement, payment or measured result exists.
- All prices are unvalidated hypotheses, not revenue.
- These files are **not** customer evidence and must never be recorded as such.

| Document | Purpose | Audience | Review status | Outstanding decisions | SHA-256 |
|---|---|---|---|---|---|
| `README.md` | Index and status of the package | Internal | Draft | — | `abba34a2ff1b3dd2e3493b7dc67cf7dfd496c38806185a820823d95562c973e4` |
| `01_offer_overview.md` | Problem, bounded scope, deliverables, exclusions, options and indicative prices | Customer-facing after review (remove OPERATOR NOTE blocks) | Draft — prices are unvalidated hypotheses | Approve or edit scope and the three prices ($0 / $1,500 / $5,000); decide payment terms | `16bc96b832431d66a33b5cb0df4a7b8019587a556e0cd473495f5e51d921eff6` |
| `02_consent_and_data_handling_DRAFT.md` | Plain-language consent and data-handling proposal | Customer-facing ONLY after legal review | Draft — REQUIRES LEGAL REVIEW; not approved for use | Legal review; retention period; contact details; consent signature method; disclosure that record metadata survives deletion | `edf33cf6a00da93f18fc004104a73f72e3fa2d4f9a561dd7378cdcaa92872fdb` |
| `03_discovery_checklist.md` | Questions for the free discovery conversation | Operator | Draft | Confirm the questions and red flags | `a1fb580fd6c164bc794f7a5f86b92358525cbb118c4eb16bf1ccdec62e37ac9c` |
| `04_outcome_specification_template.md` | Deliverables and acceptance criteria fixed before work | Shared with the customer | Draft template | Confirm AC-1 to AC-8 as the default criteria | `98041ee2b9ce6fe5a02622ecdbd70c93d0b8e67bc2019514c81f65009792127b` |
| `05_sample_deliverable_structure.md` | Outline of the report a customer would receive (no findings) | Customer-facing | Draft | Confirm report structure | `45cdc30d7fecf2b39909e45d9f037c2fc4e8b35f8cc1ba5aea5aeddf78b7560a` |
| `06_commercial_evidence_checklist.md` | Evidence required for each commercial claim, mapped to existing records | Internal | Draft | Approve a payment-reconciliation policy before any payment is counted | `7999ac1c1ae27b0eee53a9f540a631dabe1d491536168ef31c10c3271b393591` |
| `07_operator_execution_checklist.md` | Twelve auditable steps from first contact to the promotion decision | Internal | Draft | Choose the first prospect; authorize contact | `19a56f6fd8daff8d2e1d95296082bafb6981637503cafc744a93fe591bf3d110` |

## Outstanding decisions (operator)
1. Approve or edit the offer, scope and the three indicative prices.
2. Arrange legal review of the consent text and any terms; set the retention period.
3. Decide payment terms and approve a payment-reconciliation policy.
4. Decide whether the first proposal can go out unsigned or waits for delivery signing.
5. Choose one real prospect and authorize contacting them.

## Verification
Run `sha256sum -c SHA256SUMS` inside `docs/commercial/`. `SHA256SUMS` covers the eight documents and this manifest.
