# Phone-to-repository capture workflow (Termux)

Exact, copyable commands. No abbreviation, no placeholder report — every
command below is one that was actually exercised (against fixture data,
not a phone) while building this mission; see
`perception/reports/PROOF_001_EXECUTION_REPORT.md` for the runs.

## 0. One-time setup

```bash
pkg install -y python git termux-api
termux-setup-storage   # grants Termux access to /sdcard, one-time prompt
cd ~
git clone https://github.com/jamdav688y-source/forgeworld-runtime.git
cd forgeworld-runtime
git checkout claude/perception-gateway
```

If the repository is already cloned, pull the latest Perception Gateway
code instead:

```bash
cd ~/forgeworld-runtime
git fetch origin
git checkout origin/claude/perception-gateway -- perception/
```

## 1. Capture a screenshot on the phone

Standard Android screenshot (power+volume-down, or your device's gesture).
Screenshots land in `/sdcard/Pictures/Screenshots/` on stock Android; some
OEMs use a different path — check with:

```bash
ls /sdcard/Pictures/Screenshots/ 2>/dev/null || find /sdcard -iname "Screenshot_*.png" -newer /sdcard/DCIM 2>/dev/null | tail -5
```

## 2. Ingest it (CAPTURE + HASH) — governed, copy-not-alter

```bash
cd ~/forgeworld-runtime
./perception/scripts/forge-perception ingest \
  /sdcard/Pictures/Screenshots/Screenshot_YYYYMMDD_HHMMSS.png \
  --capture-source termux_phone_capture \
  --device-note "$(getprop ro.product.model 2>/dev/null || echo unknown-device)"
```

This prints the resulting `VisualObservation` JSON, including
`source_image_sha256` — note it, the next step needs it. The original file
on `/sdcard` is never modified; a governed copy is stored under
`perception/data/images/<sha256>.png` (gitignored — this is runtime state,
not something committed to the repo).

## 3. Run the pipeline

Fully offline by design (see `perception/src/ocr.py` /
`perception/src/retrieval.py`'s documented-but-unwired real-provider
extension points). Supply OCR text and retrieval candidates as JSON
fixture files — for a first real run, start from the committed samples and
edit them:

```bash
cp perception/fixtures/ocr_fixtures.json /sdcard/my_ocr_fixture.json
cp perception/fixtures/retrieval_fixtures.json /sdcard/my_retrieval_fixture.json
# edit /sdcard/my_ocr_fixture.json: replace the sha256 key with the one
# printed in step 2, and set "text" to what you actually see on screen.

./perception/scripts/forge-perception run \
  /sdcard/Pictures/Screenshots/Screenshot_YYYYMMDD_HHMMSS.png \
  --capture-source termux_phone_capture \
  --ocr-fixtures /sdcard/my_ocr_fixture.json \
  --retrieval-fixtures /sdcard/my_retrieval_fixture.json
```

Omit `--decided-by` (as above) to stop the run at CAPABILITY PROPOSAL —
the honest default. Proposals are printed, but nothing is promoted yet.

## 4. Review pending proposals

```bash
./perception/scripts/forge-perception review
```

## 5. Human promotion decision

Only a human may run this step — it is the mission's Human Promotion Gate,
enforced structurally (`PromotionDecision.provider` is always `null`):

```bash
./perception/scripts/forge-perception promote PRP-xxxxxxxxxxxx --actor "human:$(whoami)"
```

If `PROMOTED`, the proposal is written to the Knowledge Vault
(`perception/ledgers/knowledge_vault.jsonl`, gitignored — inspect it
directly, or:)

```bash
./perception/scripts/forge-perception vault
```

## 6. Status at any time

```bash
./perception/scripts/forge-perception status
```

## Notes

- Steps 2–6 never touch git — nothing is committed automatically. If you
  want to preserve a particular run's ledger/vault state in the repository
  (e.g. for a report), copy the relevant `.jsonl` files out of the
  gitignored `perception/ledgers/` / `perception/data/` directories
  explicitly and add them under `perception/reports/` or similar, the same
  way `perception/reports/proof_001_run_output.json` was captured for this
  proof.
- `ingest` is idempotent: re-running it on the same file (same bytes) is a
  no-op that returns the same `VisualObservation`.
- If OCR/retrieval fixture files reference a sha256 that does not match
  the actual ingested image, `forge-perception run` will still execute —
  the OCR provider simply returns empty text for an unregistered sha256
  (fail closed, never fabricated) rather than erroring.
