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

## Register the operator (once per device)

```bash
omega operator-init --name <you>      # asks for a passphrase (10+ characters) twice; it is never stored
```

Consequential commands (`pair`, `revoke`, `task-authorize`, `delete`, `verify-payment`,
`retention`) ask for this passphrase each time. Without it, nothing on the device (an AI agent
included) can authorize an external action, delete data, or confirm a payment. The setup
scripts run `operator-init` for you.

## Pair the two devices (once)

On each device: `omega offer` → copy the `FWPAIR1:…` text to the other device (paste, QR, file).
The offer carries the operator's public key, and the 6-digit SAS covers it.

```bash
# phone (scripts/omega-pocket.sh …) and PC (.\scripts\omega-forge.ps1 …), each with the OTHER's offer:
omega pair --offer <their offer> --my-offer <my offer>
#  -> prints "SAS: 123456"; check BOTH screens show the same 6 digits, then:
omega pair --offer <their offer> --my-offer <my offer> --sas 123456 [--max-privacy PRIVATE]   # asks for the passphrase
```

## Synchronize

* **Same network:** on the PC, `omega serve --host <PC LAN IP> --port 47470`; on the phone,
  `omega sync --host <PC LAN IP> --port 47470 --peer <PC device_id>`. Optional discovery:
  `omega announce` / `omega discover`. Allow TCP 47470 (and UDP 47474 for discovery) through the
  Windows firewall for the private network only.
* **Never online together:** `omega bundle-export --peer <id> --out phone.fwbundle`, carry the
  file over by any means, then `omega bundle-import phone.fwbundle`. The file is encrypted to the
  recipient and signed by the sender.

Sync never executes tasks. To act: `omega task-list`, `omega task-authorize --task <id>` (asks for
the passphrase) **on the device that will act**, then `omega task-run`.

## Prove it on this machine

`scripts/omega-proof.sh "<device>"` (Termux/Linux) or `.\scripts\omega-proof.ps1 -Device "<device>"`
(Windows) writes a signed proof file. See PHYSICAL_PROOF_PROTOCOL.md.

## Verify an installation

```bash
python -m omega verify                # exit 0 = every id, signature, chain, receipt verifies
python -m omega.demo_e2e --workdir /tmp/omega-demo   # full acceptance scenario on one machine
python -m pytest -q omega/tests
```
