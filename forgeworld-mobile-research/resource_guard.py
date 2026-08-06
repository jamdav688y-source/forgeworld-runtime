"""Mobile resource governance: GREEN/YELLOW/ORANGE/RED, per the project's
battery/thermal/memory/storage rules.

This module has no sensor access of its own in this environment -- there
is no phone connected to read real battery/thermal state from. Every
function here accepts metrics as arguments (battery percent, charging
state, free memory, free storage, thermal reading, queue depth) rather
than reading them itself, so the exact same logic is real and correct
whether the caller is:
  - this Linux container feeding it synthetic values for testing, or
  - a real Termux process on the phone feeding it
    `termux-battery-status` + `/proc/meminfo` + `shutil.disk_usage` output.

MOBILE_KEEL_IDLE is the default/rest state: no active ForgeWorld task,
governed the same as GREEN but explicitly labeled so callers can tell
"idle and fine" apart from "actively working and fine."
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any


class ResourceState(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ORANGE = "ORANGE"
    RED = "RED"


MOBILE_KEEL_IDLE = "MOBILE_KEEL_IDLE"

# Thresholds -- conservative and documented, not tuned against a real
# device (no device to tune against). An operator running this for real
# should revisit these after observing actual battery/thermal behavior.
LOW_STORAGE_GB = 1.0
CRITICAL_STORAGE_GB = 0.3
LOW_MEMORY_MB = 300
CRITICAL_MEMORY_MB = 100
HIGH_THERMAL_C = 42.0
CRITICAL_THERMAL_C = 46.0
LOW_BATTERY_PCT = 20
CRITICAL_BATTERY_PCT = 10


@dataclass
class ResourceMetrics:
    """Snapshot of the inputs a resource decision is made from. Every
    field is optional -- an unmeasurable metric contributes nothing to
    the decision (never treated as "fine" by default, only as absent)."""
    free_storage_gb: float | None = None
    free_memory_mb: float | None = None
    battery_percent: float | None = None
    battery_charging: bool | None = None
    thermal_celsius: float | None = None
    active_processes: int = 0
    pending_indexing_queue: int = 0
    pending_exports: int = 0
    measured_at: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ResourceDecision:
    state: ResourceState
    reasons: list[str]
    allow_optional_indexing: bool
    allow_semantic_processing: bool
    allow_heavy_local_models: bool
    allow_media_processing: bool
    should_notify_operator: bool
    should_preserve_state: bool

    def as_dict(self) -> dict:
        d = asdict(self)
        d["state"] = self.state.value
        return d


def evaluate(metrics: ResourceMetrics) -> ResourceDecision:
    reasons: list[str] = []
    state = ResourceState.GREEN

    def escalate(new_state: ResourceState, reason: str):
        nonlocal state
        order = [ResourceState.GREEN, ResourceState.YELLOW, ResourceState.ORANGE, ResourceState.RED]
        if order.index(new_state) > order.index(state):
            state = new_state
        reasons.append(reason)

    if metrics.free_storage_gb is not None:
        if metrics.free_storage_gb <= CRITICAL_STORAGE_GB:
            escalate(ResourceState.RED, f"free storage {metrics.free_storage_gb:.2f}GB <= critical {CRITICAL_STORAGE_GB}GB")
        elif metrics.free_storage_gb <= LOW_STORAGE_GB:
            escalate(ResourceState.ORANGE, f"free storage {metrics.free_storage_gb:.2f}GB <= low {LOW_STORAGE_GB}GB")

    if metrics.free_memory_mb is not None:
        if metrics.free_memory_mb <= CRITICAL_MEMORY_MB:
            escalate(ResourceState.RED, f"free memory {metrics.free_memory_mb:.0f}MB <= critical {CRITICAL_MEMORY_MB}MB")
        elif metrics.free_memory_mb <= LOW_MEMORY_MB:
            escalate(ResourceState.ORANGE, f"free memory {metrics.free_memory_mb:.0f}MB <= low {LOW_MEMORY_MB}MB")

    if metrics.thermal_celsius is not None:
        if metrics.thermal_celsius >= CRITICAL_THERMAL_C:
            escalate(ResourceState.RED, f"thermal {metrics.thermal_celsius:.1f}C >= critical {CRITICAL_THERMAL_C}C")
        elif metrics.thermal_celsius >= HIGH_THERMAL_C:
            escalate(ResourceState.ORANGE, f"thermal {metrics.thermal_celsius:.1f}C >= high {HIGH_THERMAL_C}C")

    if metrics.battery_percent is not None and metrics.battery_charging is False:
        if metrics.battery_percent <= CRITICAL_BATTERY_PCT:
            escalate(ResourceState.RED, f"battery {metrics.battery_percent:.0f}% <= critical {CRITICAL_BATTERY_PCT}% and not charging")
        elif metrics.battery_percent <= LOW_BATTERY_PCT:
            escalate(ResourceState.YELLOW, f"battery {metrics.battery_percent:.0f}% <= low {LOW_BATTERY_PCT}% and not charging")

    if metrics.pending_indexing_queue > 50:
        escalate(ResourceState.YELLOW, f"indexing queue depth {metrics.pending_indexing_queue} > 50")

    if not reasons:
        reasons.append("all measured metrics within normal range")

    return ResourceDecision(
        state=state,
        reasons=reasons,
        allow_optional_indexing=state in (ResourceState.GREEN,),
        allow_semantic_processing=state in (ResourceState.GREEN,),
        allow_heavy_local_models=state in (ResourceState.GREEN, ResourceState.YELLOW) and (
            metrics.battery_charging is True or metrics.battery_charging is None
        ),
        allow_media_processing=state in (ResourceState.GREEN, ResourceState.YELLOW),
        should_notify_operator=state == ResourceState.RED,
        should_preserve_state=state in (ResourceState.ORANGE, ResourceState.RED),
    )


def write_state_snapshot(metrics: ResourceMetrics, decision: ResourceDecision, out_path: Path) -> None:
    """Atomic-ish write of the current resource snapshot, for the Status
    tab / /api/system_status to read without recomputing."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    payload: dict[str, Any] = {
        "metrics": metrics.as_dict(),
        "decision": decision.as_dict(),
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(out_path)
