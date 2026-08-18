# End-to-End Evidence Package

## Completion-gate trace (mission Section 22)

Proven by `whatsapp/tests/test_e2e_sandbox.py::test_full_pipeline_sandbox_run`, run against sanitized
fixtures with a fully reconstructable execution-ledger trace:

```
AUTHORIZED MESSAGE RECEIVED     -> webhook_adapter.process_webhook_payload() [signature verified]
  -> AUTHENTICATED              -> provenance.webhook_verified == True
  -> NORMALIZED                 -> normalize.normalize_message() -> canonical event (schema-validated)
  -> LEDGERED                   -> conversation_ledger.jsonl entry
  -> CLASSIFIED                 -> classify.classify() -> intent/risk/evidence_sufficiency
  -> CONTEXT RETRIEVED          -> draft.compile_draft() reads memory/memory.log
  -> RESPONSE DRAFTED           -> execution_ledger: state=READY_FOR_HUMAN_APPROVAL
  -> AUTHORITY ENFORCED         -> premature send attempt -> BLOCKED_BY_AUTHORITY (proven, not assumed)
  -> APPROVED                   -> approval.approve() -> state=APPROVED_AWAITING_SEND
  -> DELIVERED                  -> outbound.send() [sandboxed transport] -> SAFE_AUTOMATION_EXECUTED
  -> DELIVERY STATUS RECONCILED -> reconcile.apply_status_event() -> VALIDATED_COMPLETE
  -> OUTCOME RECORDED           -> execution_ledger.jsonl full trace, queryable by draft_id
  -> NO GOVERNANCE REGRESSION   -> test_no_governance_regression_when_credentials_absent proves
                                    the same chain fails closed (BLOCKED_BY_CONFIGURATION) with no
                                    credentials, which is the actual current deployment state
```

## Test run

```
$ python3 -m unittest discover -s whatsapp/tests -p "test_*.py"
...........................................
----------------------------------------------------------------------
Ran 43 tests in 0.042s

OK
```

43/43 passing. Coverage against the mission's required test list (Section 19), scoped to what's
testable without live Meta credentials:

| Required test | Covered by |
|---|---|
| Valid webhook | `test_webhook_adapter.test_valid_webhook_is_accepted_and_ledgered` |
| Invalid verification | `test_invalid_signature_is_blocked_by_policy` |
| Forged request | `test_forged_request_with_no_signature_header_is_blocked` |
| Malformed payload | `test_malformed_json_payload_is_revision_required` |
| Duplicated message | `test_duplicate_delivery_is_deduped_not_double_ledgered` |
| Reordered status event | `test_status_event_is_ledgered_regardless_of_arrival_order` |
| Unsupported message type | `test_unsupported_message_type_degrades_to_unknown_not_dropped` |
| Prompt injection in a message | `test_classify.test_prompt_injection_text_is_classified_as_data_not_instruction`, `test_authority.test_prompt_injection_cannot_elevate_authority` |
| Contact without opt-in / revoked consent | `test_consent.*`, `test_outbound.test_blocked_by_consent_when_revoked` |
| Message requiring a template / expired service window | `test_outbound.test_send_outside_csw_without_template_is_blocked_by_policy`, `test_send_outside_csw_with_template_succeeds` |
| Invalid token / model outage equivalent | `test_outbound.test_blocked_by_configuration_without_credentials` |
| Insufficient evidence | `test_classify.test_sensitive_data_forces_insufficient_evidence_and_high_risk` |
| Sensitive information | same |
| Unauthorized price commitment | `test_draft.test_pricing_draft_avoids_stating_a_price` |
| Approval rejection / escalation | `approval.py` covered via `test_e2e_sandbox`; reject/escalate paths exercised in `governance/05_AUTHORITY_MATRIX.md`-matching authority tests |
| Outbound delivery failure | `outbound.send()` `REVISION_REQUIRED` path on `URLError` (not unit-tested directly — no live transport to fail; documented as an out-of-scope live-only case) |
| Successful send / delivered / read reconciliation | `test_outbound.test_free_form_send_succeeds_within_csw_with_credentials`, `test_reconcile.*` |
| Emergency stop | `test_authority.test_emergency_stop_blocks_send`, `test_outbound.test_emergency_stop_blocks_send_even_when_approved_and_configured` |
| Trace reconstruction | `test_e2e_sandbox.test_full_pipeline_sandbox_run` (final assertion block) |

Not covered (documented, not silently skipped — no live infrastructure exists to test against):
rate limiting, mTLS, malware/AV scanning of real media, live network failure modes beyond
`URLError` handling, deletion/legal-hold workflows beyond the design in
`governance/04_PRIVACY_RETENTION_MODEL.md`.

## Governance artifacts

- `governance/00_DISCOVERY_REPORT.md` — what exists vs. what was built
- `governance/01_PLATFORM_POLICY_EVIDENCE.md` — live-verified Meta platform rules, dated
- `governance/02_ADR.md`, `03_THREAT_MODEL.md`, `04_PRIVACY_RETENTION_MODEL.md`, `05_AUTHORITY_MATRIX.md`
- `reports/claims_integrity_report.md` — this increment's honesty check
