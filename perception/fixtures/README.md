# Perception Gateway fixtures

## On 1554.png / 1555.png

The mission brief for FORGEWORLD PERCEPTION GATEWAY — PROOF 001 asks to
"Use the supplied screenshots corresponding to 1554.png and 1555.png."
No such files exist anywhere in this repository or the working environment
this proof was executed in — confirmed by exhaustive filesystem search (see
`perception/governance/00_DISCOVERY_REPORT.md`'s "Fixture discrepancy"
section for the exact search performed). Silently substituting other images
and calling them "1554.png"/"1555.png", or fabricating a claim that the
named files were used, would misrepresent what was actually tested.

Instead, this directory contains clearly-labeled **synthetic** stand-ins
that exercise the exact scenario the acceptance tests describe:

| File | Role |
|---|---|
| `screenshot_1554.png` | Synthetic "screenshot A" |
| `screenshot_1555.png` | Synthetic "screenshot B" — a near-duplicate of A (same pattern, one pixel nudged, simulating recompression/re-capture noise). Its sha256 is, and must always be, different from A's. |
| `screenshot_different.png` | A genuinely different synthetic image — the negative control for near-duplicate detection. |

Generated deterministically by `generate_fixtures.py` (pure stdlib, no
external images, no randomness — same bytes on every run; run `python3 -m
perception.fixtures.generate_fixtures --verify` to check the checked-in
files still match). `ocr_fixtures.json` and `retrieval_fixtures.json` key
their entries off these files' actual sha256 digests, computed once and
pinned as constants.

## Bonus: a real screenshot

Alongside the synthetic set, this proof's execution report additionally
runs the full pipeline against one genuinely real Android screenshot that
*was* available in the working environment during this mission (an
unrelated image, not 1554/1555) — see the Proof 001 execution report for
that run's output, clearly labeled as the real-image supplement rather
than a stand-in for the missing named files.

## Provenance

Every fixture here is synthetic, procedurally generated, or (the one
exception, clearly labeled above) a real image already present in this
session's working environment before this mission began. Nothing here is
sourced from live traffic or a third party. Do not add real, unreviewed
screenshots to this directory — generate new synthetic fixtures by
extending `generate_fixtures.py` instead, matching the convention already
established in `whatsapp/fixtures/README.md`.
