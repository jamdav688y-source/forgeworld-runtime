# Regression Report: commit 3a8ca86

**Environment:** Linux cloud container (x86_64 VM, 4 vCPU), Python 3.13.18, SQLite 3.53.1 with FTS5, cryptography 50.0.1, pytest-randomly for ordering; Ollama 0.40.16 with `qwen2.5:1.5b` where noted. **These are not phone or PC results.**

| Run | Command | Before (`c9a53c0`) | After (`3a8ca86`) |
|---|---|---|---|
| Isolated experiment ×30 | `pytest omega/tests/test_experiment.py::test_full_experiment_over_loopback` | 18 pass / 12 fail | **30 / 0** |
| Full suite, 8 random orders | `pytest -p randomly --randomly-seed=1..8 omega/tests` | 3 clean / 5 failed | **8 / 8 clean**: 97 passed, 1 skipped each, 20–21 s |
| Full suite, fixed order | `pytest -p no:randomly omega/tests` | — | 97 passed, 1 skipped |
| Full suite with local Ollama (fresh clone, via the gate) | `python -m omega.gate --ollama-model qwen2.5:1.5b` | — | **101 passed, 0 skipped**, 21 s; verdict PASS |
| Benchmark score pins | `pytest omega/tests/test_bench.py` | — | pins unchanged (rules F1 0.68 etc.) |
| Cognition (legacy) | `python -m unittest discover -s cognition/tests -t .` | 388 OK | **388 OK** |
| Legacy pytest suites | `pytest evidence_envelope/tests capabilities/tests forgeworld-mobile-research/tests` | 117 + 2 skipped | **117 passed, 2 skipped** |
| Android script dry run | `HOME=<tmp> bash android-verify.sh 3a8ca86…` (Linux, not Termux) | — | installed `3a8ca86…`, verdict PASS |

**Counts:** the suite grew from 96 to 101 tests (+2 ordering regressions, +3 gate tests). Without a model server it is 100 passed and 1 skipped.

**Covered by this suite, and passing in every run above:**
* offline capture (`no_network`)
* restart persistence, including a kill mid-transaction
* idempotent sync (second session moves 0 events)
* interrupted sync resume
* unauthorized-action rejection (operator attestation, forged rows, model actors)
* replay rejection
* evidence signing and tamper detection

**Skips:**
* `test_bench.py::test_real_local_model_adds_advisory_warning`: skipped only when no Ollama server with `qwen2.5:1.5b` is running. **Release relevance:** none for the phone (the model advisor is optional and WARN-only); relevant for the PC, which should run it (`-Model qwen2.5:1.5b`).
* 2 legacy skips: Windows-only capability probes; they run on Windows.

**Governance invariants unchanged:** append-only triggers, operator attestation, local authorization, privacy clearance, and replay protection. No code in `events.py`, `policy.py`, `store.py`, `sync.py`, `tasks.py` or `operator.py` changed in this fix.

Evidence: [`post-fix-3a8ca86/`](post-fix-3a8ca86/), with a signed gate report (`python -m omega.proof verify docs/omega/stabilization/post-fix-3a8ca86/gate_report.signed.json` → `untampered: true`).
