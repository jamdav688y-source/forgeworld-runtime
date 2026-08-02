# Baseline Preservation

## Prior baseline

None existed. See `.forge/AUDITS/cinema_final_recovery.md` and
`.json` -- an exhaustive search of this repository and session found no
prior Cinema Engine, Cinema Player, genome, scene, or release artifacts
of any kind. `FW-CINEMA-PLAYER-90S-V1` is the first baseline, not a
continuation of one.

## How this baseline is itself preserved for future cycles

- Committed to the `forgeworld-runtime` repository on branch
  `claude/forgeworld-cinema-player-90s`, under `cinema/cinema_player_90s/`
  -- a permanent, repository-resident location, not a temporary
  session-output path.
- The release folder
  `cinema/cinema_player_90s/RELEASES/FW-CINEMA-PLAYER-90S-V1/` is
  self-contained: masters, previews, audio, continuity data, alert logs,
  scene recipes, genome manifest, and this evidence set all live
  together and are checksummed (`checksums.txt`).
- The regenerable frame cache (`renderer/_frame_cache/`) is
  intentionally NOT committed (see `.gitignore` and
  `known_limitations.md`) -- it's large, and it's fully reproducible from
  the committed source (`genome/`, `renderer/`) plus the same random
  seed (`genome.organism.SEED_BASE`), so committing it would be
  redundant with the code that generates it deterministically.
- Any future cycle building `FW-CINEMA-PLAYER-90S-V2` or later should:
  1. Treat this release folder as read-only prior art -- don't overwrite it.
  2. Read `MANIFESTS/source_map.json` and `GENOME/genome_manifest.json`
     first to find and reuse existing primitives before writing new ones.
  3. Create a new `RELEASES/FW-CINEMA-PLAYER-90S-V2/` (or similarly
     versioned) folder alongside this one, following the same structure.
