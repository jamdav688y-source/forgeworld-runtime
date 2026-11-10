# Cross-Device Release Gate

| # | Gate | Required evidence | Status |
|---|---|---|---|
| 1 | Clean, reproducible regression | repeated + random-order full suite, legacy suites | **PASSED (container)**: REGRESSION_REPORT.md |
| 2 | Root cause of the device failure fixed with a regression test | test fails on old code, passes on new | **PASSED (container)**: ROOT_CAUSE_REPORT.md |
| 3 | Governance invariants preserved | attestation, authorization, replay, append-only tests | **PASSED (container)** |
| 4 | Android gate PASS at the fixed commit | signed `report.json` from Termux, `verdict: PASS` | **OPEN**: owner action |
| 5 | Windows gate PASS (with model) | signed report from Windows | **OPEN** |
| 6 | Physical experiment | `verdict.json` from `omega.experiment report` with `all_ok: true` (enforced: phone record must be Android/Termux, PC record must be Windows) | **OPEN** (needs 4 and 5) |
| 7 | Owner review and merge of PR #12 | owner decision | **OPEN**: not to be merged by Claude |

**Release decision now: NOT RELEASED.** Gates 1–3 are complete in simulation. Gates 4–6 need the physical devices; gate 7 needs the owner.

Rules:
* a container, Linux or loopback result never satisfies gates 4–6;
* any FAIL verdict blocks the release until it is root-caused like this one.
