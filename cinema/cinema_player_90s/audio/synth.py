"""Synthesized audio system: ten 90-second stereo stems built from the
same CognitiveState timeline that drives the visuals, so audio and image
develop together instead of being scored independently after the fact.

Everything here is numpy oscillator/noise synthesis -- no samples, no
external audio library, no recorded material. Stated plainly in
audio_provenance.json / AUDIO/audio_validation.md.
"""
from __future__ import annotations

import numpy as np

from genome.state import TOTAL_FRAMES, FPS, SCENES, state_for_frame

SAMPLE_RATE = 48000
DURATION_S = 90.0
N_SAMPLES = int(SAMPLE_RATE * DURATION_S)

STEM_NAMES = [
    "atmosphere", "cognitive_pulse", "sensory_signals", "executive_selection",
    "construction", "validation", "emergence", "release", "recursion", "narration",
]


def _time_axis() -> np.ndarray:
    return np.linspace(0, DURATION_S, N_SAMPLES, endpoint=False)


def _sample_index_to_video_frame(t: np.ndarray) -> np.ndarray:
    return np.clip((t * FPS).astype(int), 0, TOTAL_FRAMES - 1)


def metric_envelope(metric_name: str, t: np.ndarray | None = None, stride: int = 4) -> np.ndarray:
    """Full-sample-rate envelope for a CognitiveState metric, built by
    sampling every `stride`-th video frame (fast) and linearly
    interpolating up to audio sample resolution (smooth)."""
    if t is None:
        t = _time_axis()
    sample_frames = list(range(0, TOTAL_FRAMES, stride)) + [TOTAL_FRAMES - 1]
    sample_times = np.array(sample_frames) / FPS
    values = np.array([getattr(state_for_frame(f), metric_name) for f in sample_frames])
    return np.interp(t, sample_times, values)


def _scene_window(t: np.ndarray, scene_key: str, fade_s: float = 1.2) -> np.ndarray:
    """Smooth 0..1 window that's ~1 during the named scene and fades to 0
    outside it, so a scene's stem doesn't hard-cut in or out."""
    _, _, start_f, end_f = next(s for s in SCENES if s[0] == scene_key)
    start_s, end_s = start_f / FPS, end_f / FPS
    w = np.ones_like(t)
    fade_in = (t >= start_s - fade_s) & (t < start_s)
    fade_out = (t > end_s) & (t <= end_s + fade_s)
    before = t < start_s - fade_s
    after = t > end_s + fade_s
    w = np.where(before | after, 0.0, w)
    w = np.where(fade_in, (t - (start_s - fade_s)) / fade_s, w)
    w = np.where(fade_out, 1 - (t - end_s) / fade_s, w)
    return w


def _stereo(mono: np.ndarray, width: float = 0.15, pan_lfo_hz: float = 0.0, t: np.ndarray | None = None) -> np.ndarray:
    if pan_lfo_hz and t is not None:
        pan = width * np.sin(2 * np.pi * pan_lfo_hz * t)
    else:
        pan = width
    left = mono * (1 - pan)
    right = mono * (1 + pan)
    return np.stack([left, right], axis=1)


def gen_atmosphere(t: np.ndarray) -> np.ndarray:
    maturity = metric_envelope("organism_maturity", t)
    stability = metric_envelope("structural_stability", t)
    base_freqs = [55.0, 82.5, 110.0]  # detuned low pad
    mono = np.zeros_like(t)
    for i, f in enumerate(base_freqs):
        detune = 1.0 + 0.003 * np.sin(2 * np.pi * (0.05 + i * 0.01) * t)
        mono += np.sin(2 * np.pi * f * detune * t) * (0.15 + 0.1 * stability)
    mono *= (0.3 + 0.7 * maturity)
    return _stereo(mono * 0.5, width=0.2, pan_lfo_hz=0.02, t=t)


def gen_cognitive_pulse(t: np.ndarray) -> np.ndarray:
    load = metric_envelope("cognitive_load", t)
    maturity = metric_envelope("organism_maturity", t)
    tempo_hz = 0.6 + load * 2.2  # pulse rate rises with cognitive load
    phase = np.cumsum(tempo_hz) / SAMPLE_RATE * 2 * np.pi
    pulse_shape = np.clip(np.sin(phase), 0, None) ** 3
    tone = np.sin(2 * np.pi * 60 * t) * pulse_shape
    mono = tone * (0.2 + 0.3 * maturity)
    return _stereo(mono * 0.5, width=0.05)


def gen_sensory_signals(t: np.ndarray) -> np.ndarray:
    density = metric_envelope("signal_density", t)
    window = _scene_window(t, "sensory_contact")
    rng = np.random.RandomState(90210)
    mono = np.zeros_like(t)
    n_blips = 90
    blip_times = np.sort(rng.uniform(t[0], t[-1], n_blips))
    for bt in blip_times:
        idx = int(bt * SAMPLE_RATE)
        dur = int(0.03 * SAMPLE_RATE)
        if idx + dur >= len(t):
            continue
        local_t = np.arange(dur) / SAMPLE_RATE
        freq = rng.uniform(600, 1800)
        env = np.exp(-local_t * 60)
        mono[idx:idx + dur] += np.sin(2 * np.pi * freq * local_t) * env * 0.35
    mono *= window * (0.4 + 0.6 * density)
    return _stereo(mono, width=0.3, pan_lfo_hz=0.4, t=t)


def gen_executive_selection(t: np.ndarray) -> np.ndarray:
    window = _scene_window(t, "executive_competition")
    notes = [220.0, 246.94, 277.18, 329.63, 293.66]  # small rhythmic motif
    step_s = 0.28
    mono = np.zeros_like(t)
    for i, note_t in enumerate(np.arange(t[0], t[-1], step_s)):
        idx = int(note_t * SAMPLE_RATE)
        dur = int(step_s * 0.8 * SAMPLE_RATE)
        if idx + dur >= len(t):
            continue
        local_t = np.arange(dur) / SAMPLE_RATE
        freq = notes[i % len(notes)]
        env = np.exp(-local_t * 8)
        mono[idx:idx + dur] += np.sin(2 * np.pi * freq * local_t) * env * 0.3
    mono *= window
    return _stereo(mono, width=0.15)


def gen_construction(t: np.ndarray) -> np.ndarray:
    organization = metric_envelope("pathway_organization", t)
    window = _scene_window(t, "coordinated_construction")
    rng = np.random.RandomState(4242)
    mono = np.zeros_like(t)
    n_knocks = 140
    knock_times = np.sort(rng.uniform(t[0], t[-1], n_knocks))
    for kt in knock_times:
        idx = int(kt * SAMPLE_RATE)
        dur = int(0.02 * SAMPLE_RATE)
        if idx + dur >= len(t):
            continue
        noise = rng.uniform(-1, 1, dur)
        env = np.exp(-np.arange(dur) / SAMPLE_RATE * 90)
        mono[idx:idx + dur] += noise * env * 0.5
    mono *= window * (0.5 + 0.5 * organization)
    return _stereo(mono, width=0.25)


def gen_validation(t: np.ndarray) -> np.ndarray:
    evidence = metric_envelope("evidence_intensity", t)
    window = _scene_window(t, "reality_testing")
    chord = [392.0, 493.88, 587.33]  # clean confirming chord
    mono = np.zeros_like(t)
    for f in chord:
        mono += np.sin(2 * np.pi * f * t) * 0.12
    mono *= window * (0.4 + 0.6 * evidence)
    return _stereo(mono, width=0.1)


def gen_emergence(t: np.ndarray) -> np.ndarray:
    window = _scene_window(t, "cinematic_emergence")
    palette_t = metric_envelope("palette_t", t)
    base = 330.0
    mono = np.zeros_like(t)
    for h in (1, 2, 3, 4):
        mono += np.sin(2 * np.pi * base * h * t) * (0.10 / h)
    mono *= window * (0.3 + 0.7 * palette_t)
    return _stereo(mono, width=0.3, pan_lfo_hz=0.15, t=t)


def gen_release(t: np.ndarray) -> np.ndarray:
    readiness = metric_envelope("release_readiness", t)
    window = _scene_window(t, "external_release")
    sweep = np.sin(2 * np.pi * (200 + 150 * readiness) * t)
    mono = sweep * window * 0.3
    return _stereo(mono, width=0.6, pan_lfo_hz=0.25, t=t)


def gen_recursion(t: np.ndarray) -> np.ndarray:
    memory = metric_envelope("memory_depth", t)
    window = _scene_window(t, "recursive_learning")
    motif = np.sin(2 * np.pi * 440 * t) * np.exp(-((t % 0.6)) * 6)
    delayed = np.zeros_like(motif)
    delay_samples = int(0.18 * SAMPLE_RATE)
    if delay_samples < len(motif):
        delayed[delay_samples:] = motif[:-delay_samples] * 0.5
        delayed[2 * delay_samples:] += motif[:-2 * delay_samples] * 0.25
    mono = (motif + delayed) * window * (0.3 + 0.5 * memory)
    return _stereo(mono, width=0.2)


def gen_narration_silence(t: np.ndarray) -> np.ndarray:
    # NARRATION_REJECTED (see audio_provenance.json) -- preserved as an
    # explicit silent stem rather than omitted, so the stem set matches
    # the required structure and the decision is auditable.
    return np.zeros((len(t), 2), dtype=np.float32)


STEM_GENERATORS = {
    "atmosphere": gen_atmosphere,
    "cognitive_pulse": gen_cognitive_pulse,
    "sensory_signals": gen_sensory_signals,
    "executive_selection": gen_executive_selection,
    "construction": gen_construction,
    "validation": gen_validation,
    "emergence": gen_emergence,
    "release": gen_release,
    "recursion": gen_recursion,
    "narration": gen_narration_silence,
}


def build_all_stems() -> dict[str, np.ndarray]:
    t = _time_axis()
    return {name: fn(t).astype(np.float32) for name, fn in STEM_GENERATORS.items()}


def mix_stems(stems: dict[str, np.ndarray], target_peak: float = 0.891) -> tuple[np.ndarray, dict]:
    """Sum every stem, then peak-normalize to target_peak (~ -1 dBFS) so
    the mix never clips regardless of how many stems are simultaneously
    loud. Returns (mixed_audio, provenance_info)."""
    mix = np.zeros_like(next(iter(stems.values())))
    for name, stem in stems.items():
        mix += stem
    peak_before = float(np.max(np.abs(mix)))
    gain = target_peak / peak_before if peak_before > 0 else 1.0
    mixed = mix * gain
    peak_after = float(np.max(np.abs(mixed)))
    return mixed, {
        "peak_before_normalization": peak_before,
        "gain_applied": gain,
        "peak_after_normalization": peak_after,
        "clipped": bool(peak_after > 1.0),
    }
