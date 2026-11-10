# Android Readiness

| Item | Status | Basis |
|---|---|---|
| Termux deps (Git 2.54.0, Python 3.13.13, cryptography 48.0.1, SQLite 3.53.2 + FTS5) | **Observed on device** | Owner's screenshots |
| Code installs and runs on the phone | **Observed on device** (`c9a53c0`) | Owner: 94 passed, 1 failed, 1 skipped; key_bytes, restart and e2e passed |
| The one failure | **Root-caused and fixed in `3a8ca86`** | ROOT_CAUSE_REPORT.md. The fix is **not yet run on the phone** |
| Offline capture, durable storage, restart persistence | Passed on device in the proof's `restart`/`e2e` checks (`c9a53c0`); fix not yet run there | Owner screenshots + gate |
| Signed evidence + independent verification | Proof was `untampered: true` on device | Owner screenshots |
| Phone works with the PC off | By design and tested (no network dependency) | `test_pocket_node_fully_functional_with_no_network` |
| Sync queues locally and resumes | Yes: events persist; the next session or bundle sends what is missing | `test_interrupted_sync…`, bundle tests |
| Physical experiment (section C) | **Not run** | — |

**Package:** `scripts/android-verify.sh`. It:
* checks the environment and prerequisites;
* checks out the exact commit, and refuses a checkout with local changes;
* uses a private venv with `--system-site-packages`;
* runs `omega.gate`, which prints PASS / FAIL / BLOCKED, signs a report, and keeps every run in its own evidence folder.

It writes only under `~/omega-verify`.

**Pinned file:** `scripts/android-verify.sh` at `3a8ca868ccb609dae4368e68db8d8e94941b05c6`, sha256 `ff4309de8df7679305f66903d3ba5effecb95416fb367091aa1dfa3a6088fe83`, 3553 bytes. The raw download hash was checked against the repository copy.

**Expected on the phone:** `VERDICT: PASS`, with `TESTS: 100 passed, 1 skipped` (the skip is the optional Ollama test, reported as "does not block").
