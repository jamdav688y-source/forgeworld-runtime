"""Builds every required AUDIO/ deliverable: stems, music_and_effects,
final_mix, provenance, and a validation report with real measured
numbers (peak levels, clipping check, silence check) -- not asserted
without evidence.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from audio.synth import build_all_stems, mix_stems, SAMPLE_RATE, DURATION_S, STEM_NAMES
from audio.wavio import write_wav, has_unintended_silence

NARRATION_DECISION = "NARRATION_REJECTED"
NARRATION_RATIONALE = (
    "No speech-synthesis tool is available in this environment, and the project's own law "
    "against using narration to compensate for unclear visuals rules out faking it. The "
    "narration stem is preserved as an explicit, honestly silent track rather than omitted, "
    "so the required stem structure still holds and the decision is auditable."
)


def build_audio_deliverables(out_dir: Path) -> dict:
    stems_dir = out_dir / "stems"
    stems_dir.mkdir(parents=True, exist_ok=True)

    stems = build_all_stems()
    for name in STEM_NAMES:
        write_wav(stems_dir / f"{name}.wav", stems[name], SAMPLE_RATE)

    non_narration = {k: v for k, v in stems.items() if k != "narration"}
    music_and_effects, mne_provenance = mix_stems(non_narration)
    write_wav(out_dir / "music_and_effects.wav", music_and_effects, SAMPLE_RATE)

    final_mix = music_and_effects + stems["narration"]  # narration is silence -- identical content, correct structure
    peak_final = float(np.max(np.abs(final_mix)))
    write_wav(out_dir / "final_mix.wav", final_mix, SAMPLE_RATE)

    silent_regions = has_unintended_silence(final_mix, SAMPLE_RATE)

    provenance = {
        "sample_rate_hz": SAMPLE_RATE,
        "duration_seconds": DURATION_S,
        "channels": 2,
        "stems": STEM_NAMES,
        "synthesis_method": "numpy oscillator/noise synthesis, no samples or recordings",
        "narration_decision": NARRATION_DECISION,
        "narration_rationale": NARRATION_RATIONALE,
        "mix_provenance": mne_provenance,
        "peak_final_mix": peak_final,
        "clipped": bool(peak_final > 1.0),
    }
    (out_dir / "audio_provenance.json").write_text(json.dumps(provenance, indent=2))

    validation_lines = [
        "# Audio Validation",
        "",
        f"Result: {'PASS' if not provenance['clipped'] and not silent_regions else 'WARN' if not provenance['clipped'] else 'FAIL'}",
        "",
        f"- duration: {DURATION_S} seconds (target: 90.000)",
        f"- sample rate: {SAMPLE_RATE} Hz (target: 48000)",
        f"- channels: 2 (stereo)",
        f"- peak before normalization: {mne_provenance['peak_before_normalization']:.4f}",
        f"- gain applied: {mne_provenance['gain_applied']:.4f}",
        f"- peak after normalization (final mix): {peak_final:.4f} (target <= 1.0, normalized toward ~0.891 / -1 dBFS)",
        f"- clipping: {'YES -- FAIL' if provenance['clipped'] else 'none detected'}",
        f"- unintended silence (>=2.0s, whole-mix RMS floor 1e-4): "
        f"{'none detected' if not silent_regions else silent_regions}",
        f"- narration decision: {NARRATION_DECISION}",
        f"  rationale: {NARRATION_RATIONALE}",
        "",
        "## Stems",
    ]
    for name in STEM_NAMES:
        peak = float(np.max(np.abs(stems[name])))
        validation_lines.append(f"- `{name}.wav`: peak={peak:.4f}" + ("  (silent -- narration rejected)" if name == "narration" else ""))

    (out_dir / "audio_validation.md").write_text("\n".join(validation_lines) + "\n")

    return {
        "provenance": provenance,
        "silent_regions": silent_regions,
        "final_mix_path": str(out_dir / "final_mix.wav"),
    }
