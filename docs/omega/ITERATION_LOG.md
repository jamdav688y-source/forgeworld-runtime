# Stage J — Iteration Log

Bounded iterations: each one names a measurable deficiency, a falsifiable hypothesis, the
smallest change, the focused tests, the regression run, and keep / revert.

## Baseline (iteration 0)

* Legacy suites re-run: cognition 388 passed · evidence_envelope 91 · capabilities 13 (+2
  skipped) · mobile research 13. Recorded in DISCOVERY_REPORT.md.
* The omega kernel, sync, relationship, commercial, task and evolution modules were built, with
  tests written alongside.

## Iteration 1 — the acceptance reply was not contextually advanced

* **Observation.** In the first acceptance run, the PC's authorized reply was byte-identical to
  the phone's earlier draft. It was correct, but it did not advance: the scenario never fed new
  context back.
* **Change (scenario).** The phone sends its draft and the contact answers it while the PC is
  still away. Assertion added: the PC reply must differ, acknowledge the newest answer, ask the
  next open question, and repeat nothing.
* **Result.** The assertion failed, exposing a real defect (iteration 2).

## Iteration 2 — the composer's own goal question was not recognisable

* **Deficiency (measured).** `classify_question("What would a successful outcome look like for
  you?") → None`. The answer to it was not extracted, so `goal` stayed unknown. The composer
  then asked the same question again, and `check_draft` blocked the send (`REPEATED_QUESTION`):
  the task ended FAILED. Template questions classified correctly: 6 of 7.
* **Hypothesis.** Adding the template's phrasing to the goal patterns makes 7 of 7 template
  questions classify to their own attribute, so the reply advances to `timeline`.
* **Change.** One pattern for `goal` (`successful outcome`), plus defensive patterns for
  `budget range`, `company are you`, `your role`. New invariant test
  `test_every_template_question_classifies_to_its_own_attribute`.
* **Focused tests.** The relationship suite and the e2e test pass; 7 of 7 template questions
  classify.
* **Regression.** Full omega suite: before, 56 of 57 passing (e2e failing); after, 58 of 58 (the invariant test added). Legacy suites untouched.
* **Decision.** Keep.
* Note: the safety net worked before the fix. An unrecognised repeat was caught at send time and
  the task failed closed; it did not send a repeated question.

## Iteration 3 — minor: double period in acknowledgements

* `Noted on your goal: … in half..` → strip trailing punctuation from the fact value.
* Tests: the e2e assertion now checks the exact line. Keep.

## Iteration 4 — documentation claims checked against execution

* **Deficiency.** ADR-0004 and the `identity.py` docstring claimed local memory works without
  `cryptography`. False: every append signs, so a node fails closed without it. → Corrected.
* **Deficiency.** RECOVERY_AND_ROLLBACK.md claimed a node restored from backup recovers its own
  later events from the peer. The claim was untested. → Added
  `test_restore_from_backup_then_resync_recovers_own_events` (passes), and documented that
  restored self-authorizations no longer count as local.
* **Deficiency (by inspection).** On Windows, key files opened without `O_BINARY` would be
  CRLF-translated. → Fixed. Not verified on Windows (LIMITATIONS §1).

## Stop condition

Stopped because the Stage I acceptance criteria pass on this host, and the next highest-value
deficiency (execution on a real phone and a real Windows PC with Ollama) is outside what this
environment can reach. More iterations here would not change that evidence.

---

# Directive 2 iterations

## Iteration 5 — human authorization was a string (critical)

* **Deficiency (demonstrated on `ce00f3a`).** An agent calling `TaskQueue.authorize(t, actor="human:operator")`
  made an external task run (`SUCCEEDED`). No secret was involved.
* **Hypothesis.** Requiring an attestation by a passphrase-encrypted operator key on consequential
  event types, re-verified wherever the effect is applied, makes forged authorizations ineffective,
  including rows written straight into SQLite with the device key.
* **Change.** `omega/operator.py`, `policy.ATTESTED_TYPES`, store/tasks/commercial/evolution wiring,
  the operator key in pairing offers and the SAS, a peers-table migration, a CLI passphrase prompt.
* **Tests.** `test_security_fixes.py` (10). Mutation check: removing execution-time re-verification
  fails 2 tests; removing effect verification fails 1. While writing it, I found my own forged row
  lacked the task link, so the test would have passed vacuously; fixed before relying on it.
* **Regression.** All suites green. **Keep.**

## Iteration 6 — contact ids recomputable from phone numbers

* `contact_id = H(phone number)`, visible in headers shared with peers → HMAC with a device
  secret. Demonstrated on the old commit (`True`), fixed (`test_contact_ids…`). **Keep.**

## Iteration 7 — measure repeat detection against a baseline, with real models

* Benchmark frozen first (sha `d9429aee…`), then scored. Baseline F1 0.49, rules 0.68,
  `qwen2.5:1.5b` 0.84 with 8 false alarms (rules: 2). **Decision:** the model is advisory (WARN),
  never blocking. The rules' 14 misses are listed and deliberately **not** fixed against this same
  set, which would overfit it (BENCHMARK_REPORT.md).

## Iteration 8 — the routing suite misranked real models

* The built-in 3-case suite chose `llama3.2:1b` for extraction, the worst repeat detector
  (F1 0.17). Memory-benchmark results now feed the router (`repeat_detection` → `qwen2.5:1.5b`).
  **Keep.** Growing the built-in suite remains open.

## Iteration 9 — false MISTAKEN_IDENTITY on "Hi, what's your budget?"

* Found by dry-running the LAN protocol over loopback: the case-insensitive greeting regex read
  "what's" as a name. The name must now be capitalised. Test added; benchmark scores unchanged
  (pinned by `test_bench.py`). **Keep.**

## Stop condition (directive 2)

Stopped because the next step that adds evidence is running the protocol on the owner's physical
devices, which this session cannot reach. More container-side iteration would not change the
success condition.

---

# Directive 3 (continuation and deployment)

## Iteration 10 — a published reproducibility claim was false

* **Observation.** A fresh-clone re-validation re-ran the memory benchmark. Every deterministic
  system, `qwen2.5:0.5b` and `llama3.2:1b` reproduced exactly; **`qwen2.5:1.5b` did not**
  (F1 0.836 → 0.794; 5 of 50 cases flipped). Six further runs in the new Ollama server session
  agreed with each other.
* **Conclusion.** The model is deterministic within a server session, not across restarts.
  BENCHMARK_REPORT had said "repeated runs gave identical predictions".
* **Correction.** All documents now report a range (F1 0.79–0.84, 8–10 false alarms), and the
  session-2 raw results are committed. The advisory-only policy is unaffected: in both sessions
  the model has more recall and more false alarms than the rules.

## Iteration 11 — deployment scripts and the experiment runner

* `scripts/android-verify.sh`, `scripts/windows-verify.ps1`: isolated folder, commit check,
  private venv, read-only inspection of existing installs, signed proof.
* The Android script's dry run on Linux exposed a mislabel: the proof said "(owner's phone)"
  off Termux. Now it says so only when Termux is detected.
* `omega/experiment.py` records the 14-step physical experiment as signed evidence. It passes over
  loopback (`test_experiment.py`), and its verdict is designed to stay `all_ok=false` unless the
  records come from Android **and** Windows.
