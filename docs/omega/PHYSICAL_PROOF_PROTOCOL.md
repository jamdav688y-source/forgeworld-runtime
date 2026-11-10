# Physical Proof Protocol (Windows PC + Android phone)

Status: **not yet executed on physical hardware.** This session ran in a cloud container and
could not reach the owner's machines: no Remote Control folder was available. The protocol below
is what the owner (or anyone) runs to produce the evidence. Each step writes a **signed proof
file** that anyone can check with `python -m omega.proof verify <file>`. Nothing is uploaded;
publishing the files is the owner's decision.

What a proof file shows: the exact source hashes that ran, the platform fingerprint, every check
and its raw result, and that the file was not edited afterwards. What it cannot show is which
physical device ran it. The `device` field is the operator's statement. For a public
demonstration, film the run (see YOUTUBE_PACKAGE.md).

## 0. Get the code (both machines)

```
git clone https://github.com/jamdav688y-source/forgeworld-runtime.git
cd forgeworld-runtime && git checkout ccr-0aad6294-t51qv4
```

## 1. Windows PC: items 2, 3, 4, 10

```powershell
.\scripts\omega-proof.ps1 -Device "<model, CPU, RAM> (owner's PC)"                 # without Ollama
.\scripts\omega-proof.ps1 -Device "<…>" -Model qwen2.5:1.5b -Model llama3.2:1b      # with Ollama running
```

| Check | Pass means |
|---|---|
| `test_suite` | all omega tests pass **on Windows** (the real-Ollama test runs when `qwen2.5:1.5b` is installed) |
| `key_bytes` | all 256 byte values, and 200 fresh identities (~20% contain 0x0A), round-trip byte-exactly: **the line-ending fix verified on Windows** |
| `e2e` | the acceptance scenario on Windows |
| `restart` | clean restart keeps 5/5 events; a process killed mid-transaction leaves no partial state |
| `ollama` | real models on **your** hardware: routing benchmark + memory benchmark vs baseline |

To see the original Windows defect for yourself: check out `ce00f3a`, then run
`python -c "from omega.identity import _write_secret; import pathlib; p=pathlib.Path('k'); _write_secret(p, bytes(range(256))); print(len(p.read_bytes()))"`.
**Expected: 257 on Windows (one 0x0A became 0x0D 0x0A), 256 on Linux.** That prediction is
untested; record whichever result you get.

## 2. Android phone (Termux): items 5, 6

Install Termux from F-Droid (the Play Store build is outdated), then:

```bash
pkg install -y git python python-cryptography sqlite && termux-setup-storage
git clone https://github.com/jamdav688y-source/forgeworld-runtime.git && cd forgeworld-runtime
git checkout ccr-0aad6294-t51qv4
scripts/omega-proof.sh "<phone model, Android version> (owner's phone)"
```

Platform dependencies (all checked and recorded in the proof):

| Dependency | Termux package | Fallback |
|---|---|---|
| Python ≥ 3.9 | `python` | none |
| `cryptography` | `python-cryptography` (prebuilt; pip would need Rust) | none: the node refuses to start |
| SQLite with FTS5 | bundled with `python` | `LIKE` search |
| pytest (only to run tests) | `pip install pytest` | the e2e and restart checks run without it |
| Ollama (optional) | not targeted on the phone | deterministic drafting |

**Persistence after process restart, on the device itself:** the `restart` check does this
automatically. To show it by hand:
`python -m omega init --label phone && … contact-add / message …`, then swipe Termux away or
`kill -9` it, reopen, and run `python -m omega verify` and `python -m omega context --contact <id>`.

## 3. Real two-device LAN sync: items 7, 8

On both devices, set up a real node: `scripts/omega-pocket.sh setup phone owner` on the phone,
`.\scripts\omega-forge.ps1 setup pc` on the PC. Then pair them (INSTALL.md): `omega offer` on each,
and `omega pair …` with the SAS digits compared by eye on both screens.

**Offline capture (item 8):** with Wi-Fi **and** mobile data off on the phone:

```bash
python -m omega contact-add --name "Test Contact" --primary sms:+10000000000 --actor human:owner
python -m omega message --contact <ct> --direction OUT --text "Hi, what budget do you have in mind?" --at 2026-11-10T10:00:00Z --source sms:demo#1 --actor human:owner
python -m omega message --contact <ct> --direction IN  --text "About 5k." --at 2026-11-10T10:05:00Z --source sms:demo#2 --actor tool:manual
python -m omega check-draft --contact <ct> --text "Hi, what's your budget?"      # -> REPEATED_QUESTION
```

**Later sync:** turn Wi-Fi back on. Allow TCP 47470 on the PC's *private* network profile only.

```powershell
# PC
py -m omega.proof lan-serve --home $env:USERPROFILE\.forgeworld-omega --host <PC LAN IP> --out docs\omega\proofs\lan-pc.proof.json
```
```bash
# phone
python -m omega.proof lan-sync --home ~/.forgeworld-omega --host <PC LAN IP> --peer <PC device_id> --out docs/omega/proofs/lan-phone.proof.json
```

**Duplicate prevention:** run the two commands again. The second phone proof must show
`imported: 0`, `sent: 0` and unchanged vectors. Also run `omega bundle-export` / `bundle-import`
twice: the second import must say `REPLAY_DETECTED`.

**Evidence verification:** on the PC, run `py -m omega verify` (exit 0) and
`py -m omega context --contact <ct>` (the budget fact, with the message it rests on and that
message's source `sms:demo#2`). `verify` re-checks the phone's signature on every imported event.

## 4. What to send back

Commit the proof files under `docs/omega/proofs/`, or send them, along with the outputs of
`omega.proof verify`. Any failed check is a finding, not a reason to hide the file.
