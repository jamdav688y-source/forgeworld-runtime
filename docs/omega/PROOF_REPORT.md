# Physical Proof and Demonstration — Final Report (directive 2)

## Success condition: NOT YET MET

> At least one genuinely new ForgeWorld capability demonstrated on physical hardware, measured
> against a baseline, and documented for independent reproduction.

* **Measured against a baseline, documented for reproduction: done.** The repeated-question
  memory runs with real local models (Ollama 0.40.16) and is measured against a deterministic
  baseline on a frozen benchmark, with a signed proof file and one-command reproduction.
* **On physical hardware: not done.** All execution happened in a cloud development container.
  This session had no route to the owner's PC or phone (`list_computer_folders` returned none).
  Per the directive, none of this is claimed as physical verification.
* **To close it:** about 30 minutes of the owner running PHYSICAL_PROOF_PROTOCOL.md. §1 on the
  Windows PC with `-Model qwen2.5:1.5b` alone meets the condition: a new capability (model-assisted
  repeat detection with operator-gated execution), on physical hardware, against the baseline,
  signed. Alternatively, connect the PC through Remote Control (Claude desktop app → Settings →
  Claude Code → Remote Control) and ask for the run in a new session.

The substrate is **not complete**: see the "Remaining blocker" column.

## Capability table

| Capability | Current implementation | Test performed | Actual result | Evidence artifact | Remaining blocker | Next corrective action |
|---|---|---|---|---|---|---|
| Omega test suite | `omega/tests` (94 tests) | `pytest -q omega/tests`; legacy suites re-run | 94 passed; cognition 388 OK; legacy 117 passed, 2 skipped | TEST_REPORT §2; `proofs/cloud-container.proof.json` `test_suite` | run only in the container | run on PC and phone (protocol §1–2) |
| Windows key-file handling | `_write_secret` with `O_BINARY`; byte round-trip check | 256 byte values + 200 identities round-tripped; defect frequency counted | Linux: all exact. 39/200 (19.5%) identities contain 0x0A, the population the bug affected | proof `key_bytes`; `test_key_file_bytes_round_trip_exactly` | **not run on Windows**; the original failure is predicted, not observed | protocol §1 (includes reproducing the old bug on `ce00f3a`) |
| End-to-end on Windows | `omega.demo_e2e`; `omega.proof` `e2e` check | e2e in container | all steps pass, incl. forged authorization refused | proof `e2e`; `samples/e2e_result.json` | **not run on Windows**; `.ps1` scripts never executed (no PowerShell here) | `scripts\omega-proof.ps1` |
| Android execution path | pure Python + `python-cryptography`; `scripts/omega-pocket.sh`, `omega-proof.sh` | wrapper run on Linux; dependency table written | wrapper works on Linux; Termux branch unexecuted | PHYSICAL_PROOF_PROTOCOL §2 | no Android device reachable | protocol §2 |
| Persistence after restart | WAL + one transaction per transition | separate processes: clean exit + reopen; kill inside a transaction | 5/5 kept; killed write left nothing partial; integrity ok | proof `restart`; `test_tasks_recovery.py` | Android untested (process kill by the OS) | protocol §2 (`kill -9` Termux) |
| Authenticated LAN sync | SAS pairing + operator key; X25519/Ed25519 handshake; ChaCha20-Poly1305 | `omega.proof lan-serve/lan-sync`, two CLI nodes, **loopback** | ok; second run moved 0 events; `verify` exit 0 | TEST_REPORT §4 | real Wi-Fi between devices untested (firewall, AP isolation) | protocol §3 |
| Offline capture → later sync → no duplicates → verification | `no_network()` capture; vector sync; idempotent import; signature re-check | e2e + loopback LAN + bundle replay | all pass; replay `REPLAY_DETECTED`; duplicate run imports 0 | `test_sync.py`; e2e; TEST_REPORT §4 | physical run | protocol §3 |
| Human authorization (critical defect) | `omega/operator.py`: passphrase-encrypted operator key; 7 attested event types; re-verified at execution | attack tests + mutation check; old-commit reproduction | old: agent-authorized task ran. New: refused (`OPERATOR_ATTESTATION_REQUIRED`); forged DB rows ineffective; mutations caught | `test_security_fixes.py`; TEST_REPORT §3 | passphrase capture (keylogger), no hardware keystore | improvement #2 |
| Contact-id privacy (defect) | HMAC device-secret contact ids | old-commit reproduction + test | old: recomputable (`True`); new: not | `test_contact_ids_cannot_be_recomputed…` | header metadata still visible to peers (ADR-0002) | accept for owner-only pairs, or encrypt headers per peer in v2 |
| Real Ollama model vs baseline | `OllamaClient`, `run_benchmark`, `ModelRouter` (evidence-based) | 3 real models, routing suite + memory benchmark | router chose `qwen2.5:1.5b` for repeat detection; 3-case routing suite misranked models | BENCHMARK_REPORT §2; proof `ollama` | measured on container CPU, not owner hardware | protocol §1 with `-Model` |
| Conversation-memory benchmark | `omega/bench` (50 frozen cases, sha `d9429aee…`) | baseline, rules, 3 models, rules∪model | F1 0.49 → 0.68 (rules) → 0.79–0.84 (`qwen2.5:1.5b`, 8–10 false alarms; varies across Ollama server restarts) | `benchmarks/memory_benchmark_results.json` | **same author wrote cases and rules** | improvement #1 |
| Model as advisor | `check_draft(semantic_checker=…)`: WARN only, degrades if unavailable | real-model test + fake-failure test | caught a paraphrase the rules missed (WARN); degrades to rules on failure | `test_bench.py::test_real_local_model…` | false alarms 8/19 | tune the prompt/threshold on an independent set |
| Commercial ledger | `omega/commercial.py`, separate from `cognition/commerce.py` | 4 tests (claimed ≠ verified payment, etc.) | pass; **not merged** | `test_commercial.py` | no migration / compatibility tests | improvement #3 |
| Demonstration package | `omega/showcase.py`; YOUTUBE_PACKAGE.md; CASE_STUDY.md | showcase run end to end | ~20 s, all numbers live | showcase output | physical footage requires the protocol run; publishing needs owner approval | record after protocol §3 |
| Specialist "agents" | deterministic rule checkers (`omega/agents.py`) | existing tests | advisory only | `test_evolution_agents.py` | **not model-backed**; not presented as such | — |

## Deliverables

* Runnable demonstration: `python -m omega.showcase [--pause] [--model qwen2.5:1.5b]`; full proof:
  `python -m omega.proof run --device "<machine>" --out p.json [--ollama-model M]`; wrappers:
  `scripts/omega-proof.sh`, `scripts/omega-proof.ps1`.
* Source-backed test report: [TEST_REPORT.md](TEST_REPORT.md) · benchmarks: [BENCHMARK_REPORT.md](BENCHMARK_REPORT.md)
* Physical proof protocol: [PHYSICAL_PROOF_PROTOCOL.md](PHYSICAL_PROOF_PROTOCOL.md)
* 5–8 minute narration and recording sequence: [YOUTUBE_PACKAGE.md](YOUTUBE_PACKAGE.md)
* Commercial case study: [CASE_STUDY.md](CASE_STUDY.md)

## Three highest-value next engineering improvements

1. **An independent, larger repeat-detection benchmark, then raise paraphrase recall without
   adding false blocks.** Have someone who hasn't read `relationship.py` write 200+ cases from
   real (consented, anonymised) conversations. Freeze them, and only then iterate: attribute
   synonyms for the 14 rule misses, and calibrate the model advisor (prompt or a confidence
   threshold), judged by the block-precision target ≥ 0.90. This is the product's core claim, and
   it is currently measured only on an author-written set.
2. **A hardware-backed operator key** (Windows DPAPI/TPM via `ncrypt`; Android Keystore with
   biometric prompt through a small Termux:API or Kotlin helper). It closes the at-rest and
   passphrase-capture gaps on the one control that gates every consequential action.
3. **An omega → CXP commercial bridge with migration and compatibility tests:** replay omega
   `COMMERCE_SIGNAL` / `PAYMENT_VERIFIED` events into `cognition.commerce` and assert equal
   derived state for both ledgers on shared fixtures. The two ledgers must not be merged before
   this exists (directive constraint).

(The highest-value next *action* is not engineering: run PHYSICAL_PROOF_PROTOCOL §1 on the PC.)
