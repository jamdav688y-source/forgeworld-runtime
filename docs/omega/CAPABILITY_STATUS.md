# Capability Status Matrix and Acceptance Evidence

> Directive 2 update: see [PROOF_REPORT.md](PROOF_REPORT.md) for the current table (operator
> attestation, real-Ollama benchmarks, proof harness). Physical-device status is unchanged: not run.

Run: 2026-11-10, Linux container, Python 3.13.18. Reproduce with:

```bash
python -m pytest -q omega/tests                                    # 94 passed (directive 2)
python -m unittest discover -s cognition/tests -t .                # 388 passed (unchanged)
python -m pytest -q evidence_envelope/tests capabilities/tests forgeworld-mobile-research/tests
                                                                   # 91 + 13 (2 skipped) + 13 passed (unchanged)
```

Status values follow Stage A: **VERIFIED** = executed by tests in this repository ·
**PARTIAL** = some of it verified, the rest not run · **MISSING** = not implemented ·
**BLOCKED** = cannot be done in this environment. Machine-readable: `capability_inventory.json`.

## Stage I — required tests

| # | Requirement | Test(s) | Status |
|---|---|---|---|
| 1 | Offline phone operation | `test_offline_forge.py::test_pocket_node_fully_functional_with_no_network`; `test_e2e` phase 2–3 under `no_network()` | VERIFIED on Linux (every socket creation raises) |
| 2 | Offline Windows operation | `test_forge_node_degrades_when_ollama_is_unavailable` | VERIFIED on Linux; **not run on Windows** |
| 3 | Device pairing and authentication | `test_pairing_requires_matching_short_authentication_string`, `test_man_in_the_middle_offer_changes_the_sas`, `test_unpaired_device_is_refused_by_both_sides`, `test_impostor_with_copied_device_id_fails_authentication`, `test_revoked_peer_cannot_sync`, `test_cli_…` | VERIFIED |
| 4 | Duplicate event rejection | `test_sync_converges_and_duplicates_are_rejected`, `test_novelty_and_idempotent_message_capture` | VERIFIED |
| 5 | Interrupted synchronization | `test_interrupted_sync_resumes_without_loss_or_duplication` ×5 fault points, `test_recovery_after_kill_during_import` | VERIFIED |
| 6 | Conflicting updates | `test_concurrent_conflicting_updates_are_recorded_not_merged`, `test_resolution_is_independent_of_import_order`, `test_equivocation_is_detected_and_quarantined` | VERIFIED |
| 7 | Source provenance | `test_source_artifact_stored_separately_from_derived_text`, `test_message_without_source_provenance_is_refused`, `test_answer_is_extracted_with_provenance`, e2e `pc_provenance_chain` | VERIFIED |
| 8 | Previously answered question detection | `test_previously_answered_question_is_detected_even_when_reworded`, `test_pending_question_warns_instead_of_nagging`, `test_every_template_question_classifies_to_its_own_attribute` | VERIFIED (rule-based; see limitations) |
| 9 | Cross-contact privacy isolation | `test_cross_contact_privacy_isolation`, `test_privacy_clearance_withholds_payloads_and_backfills_later` | VERIFIED |
| 10 | Commercial payment-state accuracy | `test_customer_statement_of_payment_is_never_settlement`, `test_only_humans_with_evidence_can_confirm`, `test_milestone_prerequisites` | VERIFIED |
| 11 | Replay protection | `test_replayed_hello_nonce_is_refused`, `test_replayed_or_tampered_encrypted_frame_is_rejected`, `test_offline_bundle_round_trip_replay_and_tamper`, `test_authenticated_discovery_beacon` | VERIFIED |
| 12 | Unauthorized command refusal | `test_security_fixes.py` (operator attestation, forged rows), `test_external_task_needs_local_human_authorization`, `test_model_cannot_authorize`, `test_sync_never_executes_and_remote_authorization_does_not_count`, `test_governance_and_verification_are_human_only` | VERIFIED |
| 13 | Recovery after process termination | `test_recovery_after_process_killed_mid_transaction`, `test_recovery_after_kill_during_import`, `test_internal_task_interrupted_is_requeued_external_needs_review`, `test_restore_from_backup_then_resync_recovers_own_events` | VERIFIED |
| 14 | Deterministic evidence receipts | `test_receipts_are_deterministic_for_the_same_device_and_inputs`, `test_tampered_receipt_is_detected`, `test_tampered_event_is_detected` | VERIFIED |
| 15 | Regression after capability updates | `test_real_regression_suite_gates_a_capability_update` (runs real pytest suites through the gate), `test_failing_regression_blocks_promotion`, `test_governance_change_and_weak_effect_are_not_eligible` | VERIFIED |
| E2E | Final acceptance scenario | `test_e2e.py::test_end_to_end_acceptance` (`python -m omega.demo_e2e`) | VERIFIED on one Linux host, two node stores, real TCP over loopback |

## Final acceptance condition

> two independently functional devices can preserve authorized historical knowledge, exchange
> verified evidence, reconstruct relevant context, avoid known repetition failures, and execute
> bounded tasks under human control.

**Demonstrated by reproducible tests: yes, with two independent node stores (separate keys and
databases) on one Linux machine, over real TCP on loopback.** **Not yet demonstrated: the same
on a physical Android phone and a Windows PC.** The code has no platform-specific dependency
beyond `cryptography`, but that is a code-level argument, not execution evidence. The step that
closes the gap is in LIMITATIONS.md §1.

Evidence from the acceptance run is in [`samples/e2e_result.json`](samples/e2e_result.json):
identical context digests on both nodes, the provenance chain from fact to raw SMS bytes, the
held-then-authorized task, the advanced reply (it acknowledges the newest answer, asks the next
open question, and repeats nothing), and receipts on both devices.

## Stage status

| Stage | Status | Notes |
|---|---|---|
| A Discovery | VERIFIED | DISCOVERY_REPORT.md, capability_inventory.json (validated by `test_inventory.py`) |
| B Evidence kernel | VERIFIED | all listed fields; append-only enforced by SQLite triggers |
| C Pocket substrate | PARTIAL | every minimum capability verified on Linux; not run on Termux. Optional: local LLM (via forge client), speech MISSING, semantic retrieval MISSING, offline drafts VERIFIED (deterministic) |
| D Forge substrate | PARTIAL | Ollama routing/benchmark verified against a protocol fake; multi-agent = advisory rule-based panel; repo analysis inventory-level; code generation MISSING; mission control = read-only diagnostics |
| E Sync | VERIFIED | live + bundle transports |
| F Relationship memory | VERIFIED | rule-based extraction and classification |
| G Commercial continuity | VERIFIED | |
| H Reasoning / evolution | PARTIAL | gate, rollback point and human decision verified; specialists are deterministic checkers |
| I Testing | VERIFIED | 94 omega tests + unchanged legacy suites |
| J Iteration | VERIFIED | ITERATION_LOG.md |
