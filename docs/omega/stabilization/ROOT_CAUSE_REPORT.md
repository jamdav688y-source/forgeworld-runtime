# Root Cause Report: Android "94 passed, 1 failed"

| | |
|---|---|
| Reported on device | Moto G Power (2026), Android 16, Termux, Python 3.13.13, cryptography 48.0.1, SQLite 3.53.2: full suite **94 passed, 1 failed, 1 skipped**; the isolated experiment test passed once; the proof had `test_suite: false`. *(Owner's screenshots: observed by the owner, not by this session.)* |
| Commit | `c9a53c0bad3dc0671f285a7396d64960a5a87699` |
| Failing test | `omega/tests/test_experiment.py::test_full_experiment_over_loopback` (`cmd_capture` returned False; the record showed `extracted: []`) |
| Fixed in | `3a8ca868ccb609dae4368e68db8d8e94941b05c6` |

## Reproduction (Linux cloud container, unmodified `c9a53c0`)
* Isolated test ×30: **18 pass / 12 fail**, every failure at `test_experiment.py:45` (`assert ex.cmd_capture(...)`).
* Full suite in 8 random orders (`pytest-randomly`, seeds 1–8): **5 of 8 failed** with exactly the phone's signature, `1 failed, 94 passed, 1 skipped`, always this test.
* Evidence: [`baseline-c9a53c0/`](baseline-c9a53c0/).

**Conclusion:** the failure is **random per run, not order-dependent**. The isolated pass on the phone was luck (about 60% likely), not evidence that the test was healthy.

## Mechanism (confirmed, not inferred)
`omega/experiment.py` records the question and the reply with the **same** `sent_at` (same second). `RelationshipMemory` ordered a conversation by `(sent_at, event_id)`, and `event_id` is a SHA-256 hash, so it is effectively random. Whenever the reply's id sorted below the question's:
1. `_last_outgoing_before` found no question before the reply, so nothing was extracted (`extracted: []`);
2. `context()` listed the reply before the question, so the question appeared **unanswered**.

Over 60 trials: reply id sorted first → no fact in **26/26**; otherwise the fact was extracted in **34/34**.

**Ruled out** (same results, all fresh temp dirs per test): socket and port collisions, shared databases, environment variables, SQLite locks, replay state, and test order.

## Impact beyond the test
This was a **product defect**, not only a test defect. Exported SMS and chat logs often carry second- or minute-resolution timestamps. A quick reply sharing its question's timestamp lost its answer about half the time. The repeated-question gate then failed to block a repeat, and the context misreported open questions.

## Correction (smallest root-cause fix)
`RelationshipMemory._chronological()`: sort by `(sent_at, causal rank, event_id)`. Causal rank is the number of this conversation's messages in the event's ancestry; `record_message` already makes each message a child of the previous one. The rank is computed from the signed event DAG, so **every device computes the same order**. A local insertion counter would differ between devices after a sync. No assertion was weakened, and no test was changed or skipped.

## Regression tests
* `test_reply_in_same_second_is_always_attributed_to_its_question`: 40 fresh nodes. It **failed 3/3 runs on `c9a53c0`** and passes after the fix. The chance of it passing on the defective code by luck is ≈2⁻⁴⁰.
* `test_tie_order_is_identical_on_both_devices_after_sync`: phone and PC compute the identical timeline and context digest.
