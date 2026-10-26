# Operator Execution Checklist — First Real Diagnostic (INTERNAL)

> **DRAFT FOR OPERATOR REVIEW.** Not validated with any customer.
>
> Each step is something the operator does or decides. It names what to record (the audit trail) and the gate that must hold before the next step. ForgeWorld does not perform any outreach, payment or delivery step by itself.
> Record names: commercial records use `eng-<slug>` and `acct-<slug>` pseudonyms. Never put a real name, email or phone number in a record. Keep the pseudonym-to-person mapping outside ForgeWorld.

| # | Step | Observable output / record | Gate before the next step |
|---|---|---|---|
| 1 | **Identify one real prospective customer.** Someone you can approach legitimately (existing contact, referral, inbound). | `OPPORTUNITY_IDENTIFIED` with a pseudonymous `acct-` ref and a one-line summary. No contact details. | You have personally decided to approach them. |
| 2 | **Obtain permission to discuss the operational problem.** | Written or recorded "yes, happy to talk", stored outside ForgeWorld. `INTEREST_CONFIRMED` with a `consent_ref` pointing to it. | Consent exists and you can produce it. |
| 3 | **Record the stated problem, minimally.** Run the discovery checklist (03). | The customer's statements as quoted `OBSERVATION` records (customer-sourced locators); exports only with personal data removed. | No personal or sensitive data was recorded. Spot-check every record. |
| 4 | **Decide whether it is economically meaningful.** | `ESTIMATE_RECORDED` for the customer's own cost estimate (`ESTIMATED_SAVINGS`) and for your price (`PRICE_HYPOTHESIS`). A governed research cycle over the observations, and an ORIGIN brief. | Your written go/no-go, with the reason. Stop here if the problem is too small, too vague or out of scope. |
| 5 | **Agree scope and success criteria.** Complete the outcome specification template (04) **with** the customer. | Customer confirmation of the specification, stored outside ForgeWorld. An `OUTCOME_SPEC` record (`synthetic=false`) authored by you, citing their observations and recording the engagement and the step-2 consent record (`engagement_ref`, `consent_record_id`). | Both sides confirmed **before** any diagnostic work. The criteria hash is now fixed. |
| 6 | **Review price and terms.** | Your decision on fee, payment timing and option (B or C). Legal review of terms. `PROPOSAL_SENT` with `offer_ref`, amount and document digest when the proposal goes out. | Terms reviewed. The price is still a hypothesis until accepted. |
| 7 | **Obtain consent and agreement.** | Signed consent (02, after legal review) and signed agreement. `CONTRACT_SIGNED` with document digest. | Both signed documents exist and are stored. |
| 8 | **Authorize a bounded diagnostic.** | Your written authorization naming the workflow, dates, staff contacts and data allowed. | The work stays inside this authorization. Any scope change returns to step 5. |
| 9 | **Deliver through the governed workflow.** | Delivery package bound to the spec; review by someone other than the editor; signed handoff by someone other than the editor; delivery recorded; `DELIVERY_MILESTONE`. | The package is intact (`sha256sum -c` passes) and every machine-checkable criterion passes. |
| 10 | **Record the customer's answer.** | The customer's written reply, quoted and naming the version, as an `OBSERVATION` → `CUSTOMER_ACCEPTED`, `CUSTOMER_REJECTED` or `CUSTOMER_REVISION_REQUESTED`. Commerce `CUSTOMER_ACCEPTANCE` with document digest if accepted. | A revision request → revision candidate → new version against the **same** criteria. Never edit the criteria. |
| 11 | **Verify payment and value separately.** | Payment: `PAYMENT_CONFIRMED` plus a reconciliation `VERIFICATION_RESULT` under an approved payment policy. Value: `VALUE_MEASURED` only after the proposed change ran for its validation period. | `report()` shows each stage on its own evidence. Absence stays absence. |
| 12 | **Decide on further testing or promotion.** | Your written decision, citing the DESTINATION report. `promotion_candidate()` result. | One engagement is not repeatability. Promotion needs several independent customers **and** an authorized promotion gate, which does not exist on this branch yet. |

## Stop conditions at any step
- The customer withdraws consent → stop and follow the deletion commitment.
- Sensitive personal data appears → stop, delete it, and inform the customer.
- The scope drifts beyond the authorization → return to step 5.
- Anything requires system access or credentials → out of scope; stop.
