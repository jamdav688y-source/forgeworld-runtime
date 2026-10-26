# Mission Control — Conversation-to-Opportunity Projection (SPEC, not implemented)

Status: the JSON shape that VIEW-1 will compute for one imported conversation. It narrows `MISSION_CONTROL_DATA_CONTRACT.md` to the IMPORT-1 path. No code, endpoint or frontend exists yet.

## Rules
1. **Read-only.** The projection is computed from the CXP store, delivery and destination desks, and the governor ledger. It writes nothing and calls no governed method. It also never runs `router.route()`, `discover.probe_all()`, a cycle, or any network access.
2. **Every leaf is a cell:** `{"value": …, "state": …, "sources": [...]}`.
   - `state` is one of `OBSERVED | DERIVED | HYPOTHESIS | UNVERIFIED | NOT_PROBED | UNKNOWN`.
   - `sources` holds CXP record IDs, package IDs or file digests.
   - A cell with no source has `"value": null, "state": "UNKNOWN", "sources": []`. Nothing is defaulted, estimated or filled from text.
3. **Interpretation stays separate.** Message text is shown only as the quoted OBSERVATION. Operator classifications are listed as CLAIMs beside it, never merged into it.
4. **Synthetic is visible:** `synthetic` is shown at the top level and never mixed with real rows.
5. **Deterministic:** the same store gives the same JSON, byte for byte, in canonical key order. `as_of` is the newest ledger entry time, not the wall clock.

## Input
`(customer_ref, engagement_ref, conversation_id)`, all chosen explicitly by the operator. Fuzzy lookup is not supported. If the conversation's messages name another customer, the projection reports `CROSS_CUSTOMER` and returns no rows.

## Shape
```json
{
  "projection": "conversation-opportunity/v1", "as_of": "<ledger time>", "synthetic": true,
  "customer":   {"customer_ref": CELL, "account_ref": CELL},
  "engagement": {"engagement_ref": CELL, "consent": CELL, "bound_spec_ids": CELL},
  "source_conversation": {"conversation_id": CELL, "import_files": CELL, "source_refs": CELL,
                          "first_message_at": CELL, "last_message_at": CELL, "message_count": CELL},
  "messages": [{"message_id": "...", "record_id": "...", "author": CELL, "sent_at": CELL, "text": CELL,
                "classifications": CELL}],
  "evidence_status": {"customer_message_count": CELL, "independent_origins": CELL,
                      "operator_message_count": CELL, "verification": CELL},
  "lens_analysis": {"cycles": CELL, "lens_outputs": CELL, "limitations": CELL},
  "open_contradictions": CELL,
  "opportunity_state": {"business_state": CELL, "hypotheses": CELL},
  "matched_artifacts": {"capability_matches": CELL, "packages": CELL},
  "required_human_approvals": CELL,
  "next_permitted_action": CELL
}
```

## Field sources
| Section / field | Source (existing code) | State | UNKNOWN when |
|---|---|---|---|
| **Customer and engagement** | | | |
| `customer_ref` | the operator's binding, confirmed by `customer:<ref>/conversation/<cid>/…` locators | OBSERVED (operator-assigned, **unauthenticated**) | no imported message carries it |
| `account_ref` | `COMMERCIAL_SIGNAL.account_ref` of the consent record | OBSERVED (pseudonym) | no consent record |
| `consent` | message `consent_ref` → `destination.consent_problems()` | DERIVED: `ACTIVE` / `WITHDRAWN_OR_VOIDED` (reason in value) | never: a missing record shows as `NONE` |
| `bound_spec_ids` | `OUTCOME_SPEC` records whose `engagement_ref` matches | DERIVED | none recorded |
| **Source conversation** | | | |
| `conversation_id`, `source_refs` | message `subject` (`conversation:` / `source:`) | OBSERVED | — |
| `import_files` | `import-file:sha256:<hex>` root-source locators | OBSERVED (file digest) | — |
| first / last message time, count | `observed_at` of the messages' ledger `OCCURRENCE`s | OBSERVED (export's timestamp; LinkedIn's clock, not verified) | — |
| **Verified messages** | | | |
| `text` | the OBSERVATION `statement`, unmodified | OBSERVED (QUOTATION, **UNVERIFIED**: the export's word only) | erased → `UNKNOWN`, with `erased: true` |
| `author` | `customer-author:<slug>` or `operator:<id>` from the locator | OBSERVED (operator-mapped) | — |
| `classifications` | `CLAIM`s with `derived_from = [message]` | DERIVED (one operator's label) | none recorded |
| **Evidence status** | | | |
| counts | customer- vs operator-located messages | DERIVED | — |
| `independent_origins` | `lineage.shared_origins()` over customer messages (one author is one origin) | DERIVED | — |
| `verification` | admitted `VERIFICATION_RESULT` citing a message | OBSERVED | none → `UNVERIFIED`, never `VERIFIED` by default |
| **Seven-lens analysis references** | | | |
| `cycles` | cycle artifacts whose inputs include a message (`CycleRunner.load`, tamper-checked) | OBSERVED | no human-started cycle |
| `lens_outputs` | `LENS_OUTPUT` record IDs per lens; positions only, no text inlined | DERIVED (interpretation, never evidence) | no cycle |
| `limitations` | fixed note: lens questions are media-shaped | — | — |
| **Open contradictions** | `contradiction.assess()` on `CONTRADICTION` records in those cycles | DERIVED (`OPEN` only listed) | no cycle |
| **Opportunity state** | | | |
| `business_state` | `commerce.engagement_state()` mapped per INTEGRATION_PLAN §5 | DERIVED | no commercial signal → `UNKNOWN`. **Never** inferred from message text or labels |
| `hypotheses` | `ESTIMATE_RECORDED` | HYPOTHESIS, always | none |
| **Matched artifacts** | | | |
| `capability_matches` | `origin.origin_brief()` `capabilities.matches` | DERIVED; reachability `NOT_PROBED` | no brief |
| `packages` | `DELIVERY_PACKAGE`s citing a message (`DeliveryDesk.status`, `verify().intact`) | DERIVED / integrity re-hashed | none |
| **Required human approvals** | open gates, from existing rules only: consent missing; cycle `AWAITING_HUMAN_APPROVAL`; package `VALIDATED` (review by someone other than the editor); `APPROVED_FOR_HANDOFF` (signature by someone other than the editor); `DELIVERED` awaiting a customer reply import | DERIVED | — (empty list is a value) |
| **Next permitted action** | first matching row of the table below | DERIVED | — |

## Next permitted action (fixed order; the view only names it)
| Condition | Next action | Actor |
|---|---|---|
| consent not `ACTIVE` | record consent (`INTEREST_CONFIRMED` / `PROBLEM_QUALIFIED` with `consent_ref`) | operator |
| unclassified customer messages | classify (`ConversationImporter.classify`) | operator |
| no cycle over the messages | start a cycle (R4 admits or asks a human) | operator |
| cycle awaiting human | approve or decline the R4 decision | human approver |
| no outcome spec | propose an outcome spec from the ORIGIN brief | operator |
| package `VALIDATED` | review | reviewer ≠ editor |
| package `APPROVED_FOR_HANDOFF` | sign handoff | signer ≠ editor |
| signed, not delivered | send **manually** outside ForgeWorld, then record `DELIVERED` | operator |
| otherwise | `NONE` | — |

`next_permitted_action` never executes anything. Sending, Zapier, LinkedIn and payment actions are not in the table, and VIEW-1 must not add them.

## Required tests for VIEW-1 (when authorized)
- The same store gives byte-identical JSON across a restart.
- Erasing a message turns its `text` into `UNKNOWN`.
- A conversation in another customer's locators gives `CROSS_CUSTOMER` and no rows.
- `business_state` stays `UNKNOWN` with labels present but no commercial signal.
- The view writes nothing (store snapshot unchanged) and opens no socket.
