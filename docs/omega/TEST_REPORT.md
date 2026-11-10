# Source-Backed Test Report — Omega, directive 2

Date: 2026-11-10. **Execution environment for everything below: Anthropic cloud development
container** (Linux 6.18 x86_64 VM, 4 vCPU, 15 GB RAM, Python 3.13.18, SQLite 3.53.1, cryptography
50.0.1, Ollama 0.40.16 installed in the container). **No result here was produced on the owner's
Windows PC or Android phone.** This session had no route to those devices.

Every row names the command, the observed result, and the code or artifact that backs it.

## 1. Repository state (item 1)

| Check | Command | Result |
|---|---|---|
| Working tree before this work | `git status --short` | clean; HEAD `ce00f3a` = pushed branch tip |
| Default branch | `git log origin/main -1` | `26d2ec2` (PR #11). Omega is **not merged** into main, and no PR was opened |
| Existing governance components | inspection | unchanged: `cognition/` (CXP, governor, commerce), `evidence_envelope/`, `capabilities/`, `router/`. `git diff 26d2ec2 -- cognition evidence_envelope capabilities router` is empty |
| Commercial ledger | inspection | `omega/commercial.py` stays separate from `cognition/commerce.py`. **Not merged**: no migration or compatibility tests exist yet (directive constraint) |

## 2. Test suites (item 2)

| Suite | Command | Result |
|---|---|---|
| Omega | `python -m pytest -q omega/tests` | **94 passed** (includes 1 test against a real local Ollama model; it is skipped when none is running) |
| Cognition (legacy) | `python -m unittest discover -s cognition/tests -t .` | **388 passed (OK)** |
| Legacy pytest suites | `python -m pytest -q evidence_envelope/tests capabilities/tests forgeworld-mobile-research/tests` | **117 passed, 2 skipped** (the skips are Windows-only cases) |

## 3. Defects found and fixed in this round

| Defect | How it was shown | Fix | Proof it is fixed |
|---|---|---|---|
| Any process could authorize an external action by naming `human:<x>` | On commit `ce00f3a`, a script called `q.authorize(t, actor="human:operator")` as an agent: the task ran (`SUCCEEDED`) | `omega/operator.py`: passphrase-encrypted operator key; attestation required for 7 consequential event types (`policy.ATTESTED_TYPES`), re-verified at execution | `test_security_fixes.py` (10 tests). Mutation check: with re-verification removed, 2 tests fail; with effect checking removed, 1 fails |
| A peer device could purge my data with an unattested deletion | test constructs a validly device-signed, unattested deletion | effects require a valid attestation; the event is kept as history and quarantined `UNATTESTED_*` | `test_peer_cannot_purge_my_data_without_its_operator` |
| Contact ids recomputable from a phone number, and visible in shared headers | on `ce00f3a`: `add_contact(...) == contact_id_for("sms:+15550100")` → `True` | HMAC with a device secret (`DeviceIdentity.secret_tag`); `find_contact` dedups on the same device | `test_contact_ids_cannot_be_recomputed_from_a_phone_number` |
| Windows: key files written in text mode (0x0A → 0x0D 0x0A) | code inspection; 39 of 200 fresh identities (19.5%) contain 0x0A | `O_BINARY` (committed in round 1) | `test_key_file_bytes_round_trip_exactly`; proof `key_bytes` check. **Verified on Linux only, where the bug cannot occur.** Windows run pending (PHYSICAL_PROOF_PROTOCOL §1) |
| "Hi, what's your budget?" flagged `MISTAKEN_IDENTITY` | found by the LAN-protocol dry run | the name must be capitalised; the greeting word stays case-insensitive | `test_greeting_without_a_name_is_not_mistaken_identity` |
| The 3-case routing suite picks the worst repeat detector for extraction | real Ollama run | memory benchmark results feed the router as `repeat_detection` | `test_router_uses_repeat_detection_evidence`; proof `ollama.routing.repeat_detection = qwen2.5:1.5b` |

## 4. Capabilities exercised (items 4–8, in the container)

| Item | Mechanism | Result in container | Artifact |
|---|---|---|---|
| e2e scenario | `omega.demo_e2e` | all steps pass, including forged authorization refused (`OPERATOR_ATTESTATION_REQUIRED`) and wrong passphrase refused | `proofs/cloud-container.proof.json` → `checks.e2e`; `samples/e2e_result.json` |
| persistence across restart | `omega.proof` `restart` check: subprocess writes 5 events and exits; reopen; a killed writer (`os._exit` inside the transaction) | 5/5 kept, integrity ok; after the kill still 5, integrity ok | proof `checks.restart` |
| LAN sync commands | `omega.proof lan-serve` / `lan-sync`, two CLI nodes, operator-paired, **loopback** | run 1: sent 5, imported 1, ok; run 2: sent 0, imported 0 (no duplicates); `omega verify` exit 0; PC context shows budget `5k` from `sms:demo#2` | reproduced by the commands in PHYSICAL_PROOF_PROTOCOL §3 (loopback, not LAN) |
| offline capture | `no_network()` blocks every socket during capture | capture, extraction and drafting work with sockets disabled | `test_pocket_node_fully_functional_with_no_network`, e2e phase 2 |
| replay / duplicates | bundle re-import, frame replay, nonce reuse | `REPLAY_DETECTED`, `FRAME_REPLAYED_OR_REORDERED`, `DUPLICATE` | `test_sync.py` |

## 5. Real model measurements (items 10, 11)

See BENCHMARK_REPORT.md. Headline, on 50 frozen cases (sha256 `d9429aee…`): exact-match baseline
F1 0.49 → shipped rules 0.68 (2 ms) → `qwen2.5:1.5b` 0.84 (≈350 ms, 8 false alarms vs 2).
`llama3.2:1b`: 0.17. Measured in the container on CPU, not on the owner's hardware.

## 6. Not tested (and why)

| Item | Reason |
|---|---|
| Anything on the Windows PC (items 3 verification, 4, 10 on owner hardware) | no access from this session: `list_computer_folders` returned none |
| Anything on Android (item 6) | same |
| Real LAN between two devices (item 7) | same; loopback only |
| `scripts/omega-proof.ps1`, `scripts/omega-forge.ps1` | no PowerShell in the container; never executed |
| `scripts/omega-proof.sh` under Termux | executed on Linux only (the Termux branch, `pkg install`, never ran) |
| UDP discovery across Wi-Fi | loopback only |
