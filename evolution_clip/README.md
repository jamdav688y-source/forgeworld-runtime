# ForgeWorld Evolution Clip

A minimum-viable cinematic proof: a ~23s vertical (1080x1920) clip that
visually walks FRAGMENTED EXPERIMENTS → EVIDENCE → GOVERNANCE →
ORCHESTRATION → CAPABILITY → COMPOUNDING INTELLIGENCE, then the
CAPTURE → UNDERSTAND → ORCHESTRATE → VALIDATE → COMPOUND beats, closing
on the FORGEWORLD / Governed Workflow Intelligence card.

No screenshots or external images existed in this repo or its
filesystem at build time (verified by search), so every frame is
**generated** directly from real ForgeWorld source files — governance
docs, the capability registry, the mission router, the mobile research
companion, and the scattered per-domain state files (`rpg/`, `npc/`,
`factions/`, `world/`, …). Nothing is stock footage. Every scene's exact
source file(s) are recorded in `output/MANIFEST.md` with a git blob hash
and sha256, so the provenance is checkable, not just asserted.

## Run it

```bash
./run_evolution_clip.sh              # frames + fast low-res preview
./run_evolution_clip.sh --final       # also render the full-quality export
```

Outputs land in `output/`:
- `preview.mp4` — 540x960 @20fps, ultrafast preset, for a quick look before committing to the slower final render.
- `final.mp4` — 1080x1920 @30fps, medium preset, crf 18.
- `manifest.json` / `MANIFEST.md` — per-scene provenance (source file, git blob hash, sha256).
- `frame_manifest.json` — the flat scene → frame → duration mapping used by the renderer.

## How it's built

- `assets/scenes.json` — the scene script: one entry per beat, its on-screen
  text, and the exact repo-relative files it cites.
- `assets/generate_frames.py` — Pillow-only renderer. Draws a dark
  gradient + faint hairline grid + vignette background, then restrained
  gold/white typography per scene kind (narrative card, scattered file
  fragments, evidence + citation, causal chain, orchestration split,
  capability graph, word beat, closing card). Verifies every declared
  source file actually exists before rendering.
- `assets/render.py` — assembles the PNG frames into an MP4 with
  ffmpeg's `xfade` filter (fast crossfades, no zoompan/heavy filters, so
  the graph stays small and predictable on constrained hardware).
- `assets/generate_manifest.py` — hashes every frame and every cited
  source file (sha256 + git blob sha1) and writes the provenance
  manifest.

## Dependencies

Just Python 3 + Pillow + ffmpeg — nothing else. On Termux:

```bash
pkg install python python-pillow ffmpeg git
```

The heavier `--final` encode is still cheap (a few seconds on desktop;
budget more on-device), consistent with this project's own rule that
the phone is a capture/command node, not the build engine — if a final
render is too slow on-device, run `./run_evolution_clip.sh` (preview
only) on the phone and do `--final` on the laptop.

## Design notes

- Vertical/mobile-first, dark background, restrained gold (`#c9a227`/`#e6c25c`) and warm white (`#f3efe4`) only — no other colors.
- Cinematic pacing over infographic density: one idea per card, generous negative space, 0.3s crossfades.
- Nothing here overwrites existing ForgeWorld files — this is a new, self-contained `evolution_clip/` directory.
