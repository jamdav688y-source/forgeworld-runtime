"""Minimal stereo float32 -> 16-bit PCM WAV writer (stdlib `wave` only)."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def write_wav(path: Path, stereo: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(stereo, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())


def has_unintended_silence(stereo: np.ndarray, sample_rate: int, window_s: float = 2.0, floor: float = 1e-4) -> list[tuple[float, float]]:
    """Returns [(start_s, end_s), ...] for any window_s+ stretch where the
    whole mix (not an individual stem) is below `floor` RMS -- a real
    check, not a guess."""
    window = int(window_s * sample_rate)
    mono = np.mean(np.abs(stereo), axis=1)
    silent_regions = []
    i = 0
    n = len(mono)
    while i < n:
        chunk = mono[i:i + window]
        if len(chunk) == window and np.sqrt(np.mean(chunk ** 2)) < floor:
            start = i
            j = i
            while j < n and np.sqrt(np.mean(mono[j:j + window] ** 2)) < floor:
                j += window
            silent_regions.append((start / sample_rate, min(j, n) / sample_rate))
            i = j
        else:
            i += window
    return silent_regions
