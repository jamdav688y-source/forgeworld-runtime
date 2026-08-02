# Audio Validation

Result: PASS

- duration: 90.0 seconds (target: 90.000)
- sample rate: 48000 Hz (target: 48000)
- channels: 2 (stereo)
- peak before normalization: 1.2352
- gain applied: 0.7214
- peak after normalization (final mix): 0.8910 (target <= 1.0, normalized toward ~0.891 / -1 dBFS)
- clipping: none detected
- unintended silence (>=2.0s, whole-mix RMS floor 1e-4): none detected
- narration decision: NARRATION_REJECTED
  rationale: No speech-synthesis tool is available in this environment, and the project's own law against using narration to compensate for unclear visuals rules out faking it. The narration stem is preserved as an explicit, honestly silent track rather than omitted, so the required stem structure still holds and the decision is auditable.

## Stems
- `atmosphere.wav`: peak=0.4197
- `cognitive_pulse.wav`: peak=0.2624
- `sensory_signals.wav`: peak=0.3761
- `executive_selection.wav`: peak=0.3429
- `construction.wav`: peak=0.8608
- `validation.wav`: peak=0.3719
- `emergence.wav`: peak=0.1817
- `release.wav`: peak=0.4800
- `recursion.wav`: peak=0.8945
- `narration.wav`: peak=0.0000  (silent -- narration rejected)
