# Windows Readiness

**Nothing has executed on Windows.** Every Windows statement here is code inspection or a prediction.

| Item | Status |
|---|---|
| Native test run | **Untested** |
| Key-file `O_BINARY` fix | Implemented; byte-exact on Linux and Android (where the bug cannot occur); **unverified on Windows** |
| `windows-verify.ps1` | **Never executed** (no PowerShell in the container); updated to pin the exact commit and run the gate |
| Existing ForgeWorld repository | Inspected **read-only** (`-ExistingRepo`: branch, commit, uncommitted count); never modified |
| Local model routing | Verified with real Ollama **in the container** (selects `qwen2.5:1.5b` for repeat detection); PC untested |
| Authenticated sync endpoint | `omega.experiment serve` / `omega serve`; verified over loopback only |
| Independent evidence validation | `python -m omega.proof verify <file>` runs on any machine |

**Package:** `scripts/windows-verify.ps1` at `3a8ca86`, sha256 `8130091b788cb9cb6f25c23365b10074cea1da1ab63e93528f50c027e12e06fc`. It creates `%USERPROFILE%\omega-verify` (checkout + venv + evidence). **Rollback:** delete that folder.

**Expected:** `VERDICT: PASS`, `TESTS: 101 passed` (with `-Model qwen2.5:1.5b` and Ollama running). If `key_bytes` fails, the gate says "do NOT pair this device yet".

**Known risks to watch on first run:**
* the `py` launcher may not be on PATH;
* SmartScreen or execution policy (use the `-ExecutionPolicy Bypass` form for this one run);
* a Windows Firewall prompt on `serve` (allow on Private networks only);
* antivirus file locks on SQLite WAL files (would appear as `restart` failures).
