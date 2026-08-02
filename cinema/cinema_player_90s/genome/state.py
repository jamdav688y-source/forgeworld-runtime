"""The continuous cognitive-state model that drives every scene.

This is what makes the film "one continuous cognitive organism" rather
than nine unrelated clips: every visual/camera/audio parameter for every
frame is derived from a small set of continuous scalar metrics, each of
which is defined by a keyframe value at the START and END of every scene.
Values are interpolated within a scene (eased) and simply continue from
wherever the previous scene left off -- there are no discontinuous resets
at scene boundaries, which is what makes a transition "causal" instead of
a cut.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

TOTAL_FRAMES = 2160
FPS = 24

# (name, start_frame, end_frame) -- must sum to TOTAL_FRAMES with no gaps.
SCENES = [
    ("latent_intelligence", "Latent Intelligence", 0, 192),
    ("sensory_contact", "Sensory Contact", 192, 432),
    ("neural_convergence", "Neural Convergence", 432, 720),
    ("executive_competition", "Executive Competition", 720, 984),
    ("coordinated_construction", "Coordinated Construction", 984, 1368),
    ("reality_testing", "Reality Testing", 1368, 1632),
    ("cinematic_emergence", "Cinematic Emergence", 1632, 1896),
    ("external_release", "External Release", 1896, 2088),
    ("recursive_learning", "Recursive Learning", 2088, 2160),
]

assert SCENES[-1][3] == TOTAL_FRAMES
assert all(SCENES[i][3] == SCENES[i + 1][2] for i in range(len(SCENES) - 1))
assert [f - s for _, _, s, f in SCENES] == [192, 240, 288, 264, 384, 264, 264, 192, 72]

# CAUSAL TRANSITIONS -- one per scene boundary (8 boundaries for 9 scenes).
TRANSITIONS = [
    {"from_scene": "latent_intelligence", "to_scene": "sensory_contact",
     "name": "latent pulse -> incoming signal", "at_frame": 192},
    {"from_scene": "sensory_contact", "to_scene": "neural_convergence",
     "name": "incoming signal -> normalized filament", "at_frame": 432},
    {"from_scene": "neural_convergence", "to_scene": "executive_competition",
     "name": "normalized filament -> candidate mission", "at_frame": 720},
    {"from_scene": "executive_competition", "to_scene": "coordinated_construction",
     "name": "surviving mission -> construction activation", "at_frame": 984},
    {"from_scene": "coordinated_construction", "to_scene": "reality_testing",
     "name": "constructed artifact -> validation stress", "at_frame": 1368},
    {"from_scene": "reality_testing", "to_scene": "cinematic_emergence",
     "name": "validated structure -> cinematic object", "at_frame": 1632},
    {"from_scene": "cinematic_emergence", "to_scene": "external_release",
     "name": "cinematic object -> release vessel", "at_frame": 1896},
    {"from_scene": "external_release", "to_scene": "recursive_learning",
     "name": "returning evidence -> updated memory", "at_frame": 2088},
]


@dataclass
class CognitiveState:
    frame: int
    scene_key: str
    scene_label: str
    scene_progress: float  # 0..1 within the current scene
    organism_maturity: float
    signal_density: float
    pathway_organization: float
    evidence_intensity: float
    memory_depth: float
    external_connectivity: float
    structural_stability: float
    central_geometry: float
    palette_t: float
    camera_distance: float
    cognitive_load: float
    release_readiness: float

    def as_dict(self) -> dict:
        return asdict(self)


# Keyframe targets: metric -> list of (frame, value) control points spanning
# the whole film. Values are clamped to [0, 1] and interpolated piecewise
# linearly with a smoothstep ease between control points, which is what
# makes each scene's *entry* and *exit* state match its neighbors exactly
# (the shared boundary frame has one value, not two).
_KEYFRAMES: dict[str, list[tuple[int, float]]] = {
    "organism_maturity":      [(0, 0.05), (192, 0.15), (432, 0.30), (720, 0.45),
                                (984, 0.55), (1368, 0.72), (1632, 0.85), (1896, 0.95), (2160, 1.00)],
    "signal_density":         [(0, 0.10), (192, 0.20), (432, 0.75), (720, 0.55),
                                (984, 0.50), (1368, 0.60), (1632, 0.65), (1896, 0.70), (2160, 0.40)],
    "pathway_organization":   [(0, 0.05), (192, 0.10), (432, 0.30), (720, 0.55),
                                (984, 0.65), (1368, 0.60), (1632, 0.75), (1896, 0.80), (2160, 0.85)],
    "evidence_intensity":     [(0, 0.00), (192, 0.05), (432, 0.15), (720, 0.35),
                                (984, 0.45), (1368, 0.90), (1632, 0.70), (1896, 0.55), (2160, 0.60)],
    "memory_depth":           [(0, 0.05), (192, 0.08), (432, 0.15), (720, 0.25),
                                (984, 0.35), (1368, 0.45), (1632, 0.55), (1896, 0.65), (2160, 0.95)],
    "external_connectivity":  [(0, 0.00), (192, 0.05), (432, 0.10), (720, 0.15),
                                (984, 0.20), (1368, 0.25), (1632, 0.35), (1896, 0.90), (2160, 0.75)],
    "structural_stability":   [(0, 0.20), (192, 0.20), (432, 0.30), (720, 0.35),
                                (984, 0.40), (1368, 0.35), (1632, 0.70), (1896, 0.80), (2160, 0.85)],
    "central_geometry":       [(0, 0.00), (192, 0.10), (432, 0.30), (720, 0.50),
                                (984, 0.65), (1368, 0.60), (1632, 0.80), (1896, 0.85), (2160, 0.90)],
    "palette_t":              [(0, 0.00), (192, 0.08), (432, 0.22), (720, 0.38),
                                (984, 0.50), (1368, 0.62), (1632, 0.74), (1896, 0.88), (2160, 1.00)],
    "camera_distance":        [(0, 0.85), (192, 0.75), (432, 0.55), (720, 0.60),
                                (984, 0.45), (1368, 0.40), (1632, 0.50), (1896, 0.80), (2160, 0.65)],
    "cognitive_load":         [(0, 0.05), (192, 0.15), (432, 0.45), (720, 0.70),
                                (984, 0.80), (1368, 0.85), (1632, 0.60), (1896, 0.35), (2160, 0.15)],
    "release_readiness":      [(0, 0.00), (192, 0.00), (432, 0.02), (720, 0.10),
                                (984, 0.25), (1368, 0.55), (1632, 0.80), (1896, 1.00), (2160, 0.90)],
}


def _smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _interp(points: list[tuple[int, float]], frame: int) -> float:
    for i in range(len(points) - 1):
        f0, v0 = points[i]
        f1, v1 = points[i + 1]
        if f0 <= frame <= f1:
            span = f1 - f0
            t = 0.0 if span == 0 else (frame - f0) / span
            return v0 + (v1 - v0) * _smoothstep(t)
    return points[-1][1]


def scene_for_frame(frame: int) -> tuple[str, str, int, int]:
    for key, label, start, end in SCENES:
        if start <= frame < end or (frame == TOTAL_FRAMES - 1 and end == TOTAL_FRAMES):
            return key, label, start, end
    raise ValueError(f"frame {frame} outside [0, {TOTAL_FRAMES})")


def state_for_frame(frame: int) -> CognitiveState:
    if not (0 <= frame < TOTAL_FRAMES):
        raise ValueError(f"frame {frame} outside [0, {TOTAL_FRAMES})")
    scene_key, scene_label, start, end = scene_for_frame(frame)
    span = max(1, end - start)
    progress = (frame - start) / span

    values = {metric: _interp(points, frame) for metric, points in _KEYFRAMES.items()}

    return CognitiveState(
        frame=frame,
        scene_key=scene_key,
        scene_label=scene_label,
        scene_progress=progress,
        **values,
    )


def full_timeline() -> list[dict]:
    """Every frame's state -- this is the real trace used to render, not a
    post-hoc reconstruction. Exported verbatim as CONTINUITY/cognitive_state_timeline.json."""
    return [state_for_frame(f).as_dict() for f in range(TOTAL_FRAMES)]
