# Deployment and First Physical Experiment (directive 3)

Everything here is **for the owner to run**. The coding session cannot reach the phone or the PC.
Nothing below has run on Android or Windows yet. `android-verify.sh` was dry-run on Linux
(with `HOME` redirected); `windows-verify.ps1` has never run (no PowerShell in the container).

Both scripts:
* never modify an existing installation (the Windows script only *reads* an existing ForgeWorld
  checkout if you pass `-ExistingRepo`);
* write only to `~/omega-verify` (phone) or `%USERPROFILE%\omega-verify` (PC), including a
  private Python venv;
* check the exact commit and refuse to touch a checkout that has local changes;
* upload nothing.

**Rollback:** delete that one folder.

---

## A. Android (Termux)

Termux from **F-Droid or GitHub**. The Play Store build is outdated and fails `pkg install`.

```bash
pkg install -y git python python-cryptography
curl -fsSLo ~/android-verify.sh https://raw.githubusercontent.com/jamdav688y-source/forgeworld-runtime/ccr-0aad6294-t51qv4/scripts/android-verify.sh
bash ~/android-verify.sh <COMMIT>          # <COMMIT> = the commit named in the PR / final report
```

**Expected output (in order):**
* `android_release`, `device_model`, `termux: yes`;
* `git`, `python`, `cryptography <version>`, `sqlite … fts5 yes` (or the stated `LIKE` fallback);
* `installed commit: <COMMIT…>`;
* `VERDICT: PASS` with `TESTS: 100 passed, 1 skipped` (from commit `3a8ca86`; the skip is the optional real-Ollama test). The phone run at `c9a53c0` showed 1 failure; that defect is fixed in `3a8ca86` (stabilization/ROOT_CAUSE_REPORT.md);
* a proof JSON with `"all_ok": true`, then `verify` printing `"untampered": true`;
* `proof file: /data/data/com.termux/files/home/omega-verify/evidence/android-….proof.json`.

| Symptom | Meaning | Recovery |
|---|---|---|
| `MISSING: …` (exit 2) | a package is absent | run the printed `pkg install` line, then re-run |
| `clone failed` / `fetch failed` (exit 4) | no network or GitHub unreachable | connect, re-run |
| `COMMIT MISMATCH` (exit 5) | the branch moved since the report | re-run with the new commit, or ask which one to verify |
| `Local changes … refusing` (exit 3) | you edited files under `~/omega-verify` | `rm -rf ~/omega-verify` and re-run |
| `pip install pytest` fails | no network for PyPI | the proof still runs (tests are skipped inside it); re-run later |
| any `"ok": false` check in the proof | a real finding on this phone | send the proof file. Do not edit it; edits break `untampered` |

## B. Windows (PowerShell)

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\omega-verify" | Out-Null
Invoke-WebRequest https://raw.githubusercontent.com/jamdav688y-source/forgeworld-runtime/ccr-0aad6294-t51qv4/scripts/windows-verify.ps1 -OutFile "$env:USERPROFILE\omega-verify\windows-verify.ps1"
powershell -ExecutionPolicy Bypass -File "$env:USERPROFILE\omega-verify\windows-verify.ps1" -ExpectedCommit <COMMIT> -ExistingRepo "C:\path\to\your\forgeworld" -Model qwen2.5:1.5b
```

(Before running with `-Model`, pull the model: `ollama pull qwen2.5:1.5b`, and keep `ollama serve`
or the Ollama app running.)

**Expected output:** the Windows version, Python, git and Ollama versions; the existing
checkout's branch, commit and "uncommitted entries … left untouched"; `installed commit: <COMMIT…>`;
the test summary (on Windows **with** the model, the Ollama test runs instead of being skipped);
a proof JSON with `key_bytes`, `restart`, `e2e`, `test_suite` and `ollama` all `true`; `"untampered": true`.

| Symptom | Meaning | Recovery |
|---|---|---|
| `MISSING: Python …` / `Git …` | not installed | the printed `winget install …`, open a new PowerShell, re-run |
| `key_bytes: false` | **the Windows key-file defect is not fixed on this machine**: a real finding | send the proof. Do not pair devices until it is understood |
| `ollama: false` / `UNAVAILABLE` | Ollama not running, or the model not pulled | `ollama serve`, `ollama pull qwen2.5:1.5b`, re-run |
| Windows Firewall prompt (later, section C) | `serve` opens TCP 47470 | allow on **Private** networks only |
| Script blocked by policy | execution policy | the `-ExecutionPolicy Bypass` form above applies to this one run only |

---

## C. First physical phone ↔ PC experiment

`omega/experiment.py` turns the 14 required steps into recorded, signed evidence. Use a fresh
folder for the experiment, separate from the verification folder. All data is synthetic: the
contact is "Synthetic Contact", `sms:+10000000001`.

**Prerequisites:** sections A and B passed; both devices on the same Wi-Fi network; the PC's LAN
IP (`ipconfig`, the IPv4 address).

"`python`" below means the private venv from sections A/B, run from the checkout:
* phone: `cd ~/omega-verify/forgeworld-runtime && alias python=~/omega-verify/venv/bin/python`
* PC: `cd $env:USERPROFILE\omega-verify\forgeworld-runtime; Set-Alias python "$env:USERPROFILE\omega-verify\venv\Scripts\python.exe"`

| # | Where | Command (run inside the `omega-verify/forgeworld-runtime` checkout, with the venv's python) | Directive step |
|---|---|---|---|
| 1 | phone | `python -m omega.experiment init --dir ~/omega-exp --role phone --label phone` (choose a passphrase) | setup |
| 2 | phone | **Airplane mode ON (Wi-Fi and mobile data off)**, then `python -m omega.experiment capture --dir ~/omega-exp` | 1–3 (offline; id, timestamp, source, hash recorded) |
| 3 | phone | close Termux completely (swipe away / "Exit"), reopen, `cd` back | 4 restart |
| 4 | phone | `python -m omega.experiment recall --dir ~/omega-exp` | 5–7 (persistence, continuity gate blocks the repeat) |
| 5 | PC | `python -m omega.experiment init --dir $env:USERPROFILE\omega-exp --role pc --label pc` | 8 |
| 6 | both | pair (once): on each device `python -m omega --home <dir>/node offer`; exchange the texts; on each `python -m omega --home <dir>/node pair --offer <theirs> --my-offer <mine>` → compare the **6-digit SAS** on both screens → re-run with `--sas <digits>` | 9 authenticated pairing |
| 7 | phone | airplane mode **OFF**, Wi-Fi on | — |
| 8 | PC | `python -m omega.experiment serve --dir $env:USERPROFILE\omega-exp --host <PC LAN IP>` (waits for 2 sessions) | — |
| 9 | phone | `python -m omega.experiment sync --dir ~/omega-exp --host <PC LAN IP>` | 10 sync, 12 idempotent re-sync |
| 10 | PC | copy the phone's `~/omega-exp/experiment-phone.json` to the PC (it holds no private data), then `python -m omega.experiment verify --dir $env:USERPROFILE\omega-exp --phone-record <path>` | 11, 13 |
| 11 | PC | `python -m omega.experiment report --phone <phone json> --pc $env:USERPROFILE\omega-exp\experiment-pc.json --out verdict.json` | 14 machine-readable report |

**Acceptance criteria** (all are recorded fields, not judgement):
* `capture_offline.ok`: `network_reachable_during_capture = false` and the budget was extracted;
* `recall_after_restart.ok`: a different process id; event found; payload hash and raw artifact
  match the capture; integrity ok; `continuity_gate_blocks` contains `REPEATED_QUESTION`;
* `lan_sync_twice.ok`: the first session sent more than 0 events; the second session sent 0 and imported 0;
* `serve.ok`: both sessions complete;
* `pc_verify.ok`: event present, **signed by the phone's device id**, hashes match, integrity ok,
  `same_context_as_phone = true`, and the PC's continuity gate also blocks the repeat;
* `verdict.json`: `all_ok = true`. It can only be true if the phone record's platform shows
  Android/Termux **and** the PC record's shows Windows; anyone can check it with
  `python -m omega.proof verify verdict.json`.

This exact flow passes over loopback on one Linux machine (`omega/tests/test_experiment.py`). The
same test asserts that its verdict is `all_ok = false`, because loopback on Linux is not the
physical experiment.
