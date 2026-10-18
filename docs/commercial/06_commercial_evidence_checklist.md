# Commercial Evidence Checklist (INTERNAL — operator only)

> **DRAFT FOR OPERATOR REVIEW.** Not validated with any customer.
>
> Each commercial claim needs its **own** evidence. A later stage never implies an earlier one is satisfied, and an earlier one never implies a later one. Record each item when its evidence exists, not before. Store documents outside ForgeWorld and record only a `sha256:` digest of each document in ForgeWorld records.

| # | Claim | Minimum admissible evidence | ForgeWorld record (existing) | Does **not** establish |
|---|---|---|---|---|
| 1 | **Lead** | A real person or organisation identified; source noted | `COMMERCIAL_SIGNAL` · `OPPORTUNITY_IDENTIFIED` (summary only, no contact details) | interest |
| 2 | **Interest** | The prospect agreed to discuss the problem; consent to take notes | `PROBLEM_QUALIFIED` / `INTEREST_CONFIRMED` with a `consent_ref` | agreement, need, budget |
| 3 | **Problem evidence** | The customer's own words about the problem, quoted; their exports | `OBSERVATION` records (quoted, observed), at least two independent origins where possible | that the problem is real or costly |
| 4 | **Value hypothesis** | The customer's estimate of cost; our price | `ESTIMATE_RECORDED` (`PRICE_HYPOTHESIS`, `ESTIMATED_SAVINGS`) | revenue, savings |
| 5 | **Proposal** | The proposal document sent | `PROPOSAL_SENT` with `offer_ref`, amount and document digest | agreement |
| 6 | **Agreement** | Signed agreement or written acceptance of the proposal | `CONTRACT_SIGNED` with document digest | delivery, payment |
| 7 | **Success criteria fixed** | Outcome specification confirmed by both sides before work | `OUTCOME_SPEC` (`synthetic=false`, human author) | that the work will meet them |
| 8 | **Delivery** | The exact package version handed over | Delivery package: review → signed handoff → `DELIVERED`; commerce `DELIVERY_MILESTONE` | receipt, acceptance |
| 9 | **Acceptance** | The customer's own written acceptance naming the exact version | Quoted `OBSERVATION` citing `customer:<ref>/<package>/…` → `CUSTOMER_ACCEPTED`; commerce `CUSTOMER_ACCEPTANCE` with document digest | payment |
| 10 | **Payment** | Funds received and reconciled against a payment reference | `PAYMENT_CONFIRMED` (payment-reference digest) **plus** a `VERIFICATION_RESULT` admitted by a human-approved payment policy | value to the customer |
| 11 | **Measured value** | A measurement against the agreed baseline, after the change ran | `VALUE_MEASURED` with document digest | repeatability |
| 12 | **Repeatability** | Several independent paying, accepting, measured customers | `repeatability()` reports a **candidate** at most | capability promotion |
| 13 | **Capability promotion** | A human decision through an authorized promotion gate | Not available on this branch | — |

## Rules
- Never record a stage because a later one "obviously" happened.
- Only record **synthetic** data with `synthetic` / `-synthetic-` markers, and never mix synthetic and real records in one engagement.
- Leave a stage empty if its evidence is missing. Do not fill it with an estimate.
- Fixes go forward: a mistaken record is corrected with a `CORRECTION` or `REVERSAL`. Records are never edited.
