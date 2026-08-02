# Preview Validation Report (Preview Gate)

Result: **PASS**

| Check | Result |
|---|---|
| All nine scenes present | PASS (asserted at import time in `genome/state.py`) |
| Correct chronology and frame totals (2,160 total) | PASS |
| 16:9 frame cache complete, no missing/corrupt frames | PASS (`renderer.render.verify_frame_cache`) |
| 4:5 frame cache complete, no missing/corrupt frames | PASS |
| Complete 90s audio, no clipping | PASS (`AUDIO/audio_validation.md`) |
| 8/8 causal transitions valid, continuous at every boundary | PASS (`CONTINUITY/continuity_validation.md`) |
| Media spec validation (ffprobe, both masters) | PASS (`VALIDATION/final_media_validation.md`) |
| Alert simulation: blocking alerts prevent publish, resolving/dismissing unblocks | PASS (`ALERTS/alert_simulation_report.json`) |
| No letterbox/black-band anomalies | PASS, with a caveat below |

## Letterbox check caveat

`ffmpeg cropdetect` was run against both masters. The dominant reading on
both is the full native frame (86.7% of sampled frames on the 16:9
master, 87.8% on the 4:5 master read `crop=<full width>:<full height>:0:0`
-- i.e. "nothing to crop"). A minority of frames register a smaller
suggested crop; these cluster in the darkest scene (Latent Intelligence,
near-black indigo palette) and vary frame-to-frame rather than forming a
single persistent rectangle -- consistent with `cropdetect`'s luma
threshold reacting to genuinely dark full-bleed content, not an actual
static letterbox bar. Visual confirmation: `REVIEWS/contact_sheet_16x9.jpg`
and `REVIEWS/transition_contact_sheet.jpg` show full-bleed content
(background gradient reaching every edge) at every one of the 40 sampled
frames across the film, including the darkest ones.

## What was not re-checked here (already covered elsewhere)

- No placeholder content: by construction, every frame is generated live
  by `genome/organism.py` from `CognitiveState` -- there is no
  placeholder-image fallback path in the renderer.
- Safe typography: see `REVIEWS/typography_review.md`.

## Gate outcome

All checks pass. Per the mission's Phase 10 instruction, final master
rendering proceeded automatically after this gate (see
`VALIDATION/final_media_validation.md` for the resulting master
properties) -- both were in fact rendered before this report was
finalized, since the preview and master profiles share the same
underlying frame cache (see `MASTER_SPEC.md` / `renderer/profiles.py`)
and validating the frame cache doubles as validating what both the
preview and master encodes were built from.
