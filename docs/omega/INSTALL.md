# Installation

Both nodes run the same code from this repository. Python ≥ 3.9 with SQLite (FTS5 is used when
present; otherwise search falls back to `LIKE`). The `cryptography` package is required.

## Android — pocket node (Termux)

> Not yet executed on a phone (see LIMITATIONS.md). These are the intended steps.

```bash
pkg update && pkg install -y git python python-cryptography sqlite
git clone https://github.com/jamdav688y-source/forgeworld-runtime.git ~/forgeworld-runtime
cd ~/forgeworld-runtime
scripts/omega-pocket.sh setup pocket-phone        # installs packages, creates the node
scripts/omega-pocket.sh diag                        # integrity + capability report
```

The node home is `~/.forgeworld-omega` (override with `OMEGA_HOME`). Keep it out of shared
storage: it holds the device's private keys.

Optional tests on the phone: `pip install pytest && python -m pytest -q omega/tests`.

## Windows — forge node (PowerShell)

> Not yet executed on Windows (see LIMITATIONS.md).

```powershell
git clone https://github.com/jamdav688y-source/forgeworld-runtime.git
cd forgeworld-runtime
.\scripts\omega-forge.ps1 setup forge-pc        # pip install cryptography pytest; init; diag --probe-ollama
py -m pytest -q omega\tests
```

Ollama is optional. With it installed and running (`ollama serve`, default
`http://127.0.0.1:11434`), measure the installed models on this machine, then route by evidence:

```powershell
.\scripts\omega-forge.ps1 benchmark --model llama3.2:3b --model qwen2.5:7b
.\scripts\omega-forge.ps1 route --task-class drafting
.\scripts\omega-forge.ps1 draft --contact <ct_id> --intent discovery --model <selected>
```

## Pair the two devices (once)

On each device: `omega offer` → copy the `FWPAIR1:…` text to the other device (paste, QR, file).

```bash
# phone (scripts/omega-pocket.sh …) and PC (.\scripts\omega-forge.ps1 …), each with the OTHER's offer:
omega pair --offer <their offer> --my-offer <my offer> --actor human:<you>
#  -> prints "SAS: 123456"; check BOTH screens show the same 6 digits, then:
omega pair --offer <their offer> --my-offer <my offer> --sas 123456 --actor human:<you> [--max-privacy PRIVATE]
```

## Synchronize

* **Same network:** on the PC, `omega serve --host <PC LAN IP> --port 47470`; on the phone,
  `omega sync --host <PC LAN IP> --port 47470 --peer <PC device_id>`. Optional discovery:
  `omega announce` / `omega discover`. Allow TCP 47470 (and UDP 47474 for discovery) through the
  Windows firewall for the private network only.
* **Never online together:** `omega bundle-export --peer <id> --out phone.fwbundle`, carry the
  file over by any means, then `omega bundle-import phone.fwbundle`. The file is encrypted to the
  recipient and signed by the sender.

Sync never executes tasks. To act: `omega task-list`, `omega task-authorize --task <id> --actor
human:<you>` **on the device that will act**, then `omega task-run`.

## Verify an installation

```bash
python -m omega verify                # exit 0 = every id, signature, chain, receipt verifies
python -m omega.demo_e2e --workdir /tmp/omega-demo   # full acceptance scenario on one machine
python -m pytest -q omega/tests
```
