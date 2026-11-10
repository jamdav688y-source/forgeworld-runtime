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
