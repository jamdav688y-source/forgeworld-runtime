# Capability / Authority Matrix

Mirrors mission Section 11 exactly. Enforced in code by `whatsapp/src/authority.py::required_authority()`
and `whatsapp/src/modes.py`. This file is the human-readable source of truth; the code must match it —
`tests/test_authority.py::test_matrix_matches_doc` checks the enumerated actions against this table's
action IDs.

## May execute automatically after validation

`webhook_verify`, `dedupe`, `schema_validate`, `consent_lookup`, `classify`, `summarize`,
`draft_create`, `ledger_write`, `internal_notify_low_risk`, `followup_recommend`,
`delivery_status_reconcile`, `metric_calculate`, `stopword_revoke_consent`.

## Requires explicit human approval

`first_outbound_contact`, `send_generated_answer`, `claim_forgeworld_performance`, `send_pricing`,
`send_discount`, `send_proposal`, `send_scheduling_commitment`, `send_customer_recommendation`,
`publish`, `escalate_to_person`, `process_unclear_sensitive_material`, `change_template`,
`change_campaign_audience`, `enable_higher_autonomy`.

## Prohibited without separately granted authority

`payment_or_refund`, `contract`, `legal_medical_financial_conclusion`, `delete_evidence`,
`export_contact_list`, `mass_outreach`, `identity_impersonation`, `undisclosed_surveillance`,
`bypass_optin`, `autonomous_promise`, `train_general_ai`, `unrelated_marketing`,
`contact_inferred_recipient`.

"Separately granted authority" means a signed flag in `whatsapp/config.json` under
`authority.grants[]`, set only by direct operator edit (never by the running system), each entry
carrying `action`, `granted_by`, `granted_at`, `scope`, `expires_at`. None are granted by default; this
increment ships with `authority.grants: []`.
