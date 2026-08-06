"""Mobile device discovery: produces MOBILE_DEVICE_PROFILE.json.

This is a REAL discovery script meant to run under Termux on an actual
Android phone. It has never been executed against real hardware in this
build cycle -- this code was authored and unit-tested in a Linux cloud
container that is neither Android nor Termux. Rather than fabricate
plausible-looking device facts, every field that depends on Termux/
Android-specific tooling degrades to `null` with an explicit
`not_available_reason` when that tooling isn't present, which is exactly
what happens when this module runs in this container (see
MOBILE_KNOWN_LIMITATIONS.md). The same code, run for real under Termux,
would populate these fields from `getprop`, `/proc/cpuinfo`,
`/proc/meminfo`, `termux-battery-status`, and `shutil.disk_usage`.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

# Device classification thresholds -- conservative, documented, and only
# ever applied when the underlying measurement actually exists.
LOW_RAM_MB = 3072
LOW_STORAGE_GB = 8
HIGH_RAM_MB = 8192


def detect_termux() -> tuple[bool, str]:
    termux_version = os.environ.get("TERMUX_VERSION")
    prefix = os.environ.get("PREFIX", "")
    in_termux = bool(termux_version) or "/com.termux/" in prefix
    evidence = (f"TERMUX_VERSION={termux_version!r}, PREFIX={prefix!r}, platform.system()={platform.system()!r}")
    return in_termux, evidence


def _run(cmd: list[str], timeout: float = 3.0) -> str | None:
    if shutil.which(cmd[0]) is None:
        return None
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def read_android_properties() -> dict[str, Any]:
    """Real device identity, via `getprop` -- the standard Android property
    reader, present system-wide (not Termux-specific), but only actually
    reachable when running on real Android."""
    props = {
        "manufacturer": "ro.product.manufacturer",
        "model": "ro.product.model",
        "android_version": "ro.build.version.release",
        "android_sdk": "ro.build.version.sdk",
        "build_number": "ro.build.display.id",
        "chipset": "ro.board.platform",
        "hardware": "ro.hardware",
    }
    result = {}
    any_found = False
    for field, prop in props.items():
        value = _run(["getprop", prop])
        result[field] = value or None
        any_found = any_found or bool(value)
    result["_source"] = "getprop" if any_found else None
    return result


def read_cpu_info() -> dict[str, Any]:
    arch = platform.machine()
    # Priority order matters: x86 /proc/cpuinfo has "model name" (the real
    # chip name); ARM/Android's usually only has "Hardware" instead; both
    # come after a leading "processor\t: 0" index line that looks like a
    # match on a naive "starts with a CPU-ish word" search but isn't a name.
    fields = {}
    cpuinfo_path = Path("/proc/cpuinfo")
    if cpuinfo_path.exists():
        try:
            for line in cpuinfo_path.read_text().splitlines():
                key, sep, value = line.partition(":")
                if not sep:
                    continue
                key = key.strip().lower()
                if key in ("model name", "hardware") and key not in fields:
                    fields[key] = value.strip()
        except OSError:
            pass
    model = fields.get("model name") or fields.get("hardware")
    return {"architecture": arch, "model_name": model, "logical_cores": os.cpu_count()}


def read_memory_mb() -> dict[str, Any]:
    meminfo_path = Path("/proc/meminfo")
    if not meminfo_path.exists():
        return {"total_mb": None, "available_mb": None, "_source": None}
    values = {}
    try:
        for line in meminfo_path.read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                kb = int(rest.strip().split()[0])
                values[key] = kb // 1024
    except (OSError, ValueError, IndexError):
        return {"total_mb": None, "available_mb": None, "_source": None}
    return {
        "total_mb": values.get("MemTotal"),
        "available_mb": values.get("MemAvailable"),
        "_source": "/proc/meminfo",
    }


def read_storage(path: Path) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {
            "total_gb": round(usage.total / 1e9, 2),
            "available_gb": round(usage.free / 1e9, 2),
            "path_checked": str(path),
        }
    except OSError as e:
        return {"total_gb": None, "available_gb": None, "path_checked": str(path), "error": str(e)}


def read_battery_status() -> dict[str, Any]:
    """Requires the Termux:API app + `termux-api` package -- a separate
    install from Termux itself, so this can legitimately be absent even
    on a real, correctly-set-up phone. Returns not_available_reason
    rather than guessing when it can't run."""
    raw = _run(["termux-battery-status"], timeout=5.0)
    if raw is None:
        return {"available": False, "not_available_reason": "termux-battery-status not found or failed "
                 "(requires the separate Termux:API app + `pkg install termux-api`)"}
    try:
        data = json.loads(raw)
        return {"available": True, **data}
    except json.JSONDecodeError:
        return {"available": False, "not_available_reason": "termux-battery-status returned non-JSON output"}


def read_network_interfaces() -> list[str]:
    try:
        import socket
        return [name for _, name in socket.if_nameindex()]
    except (OSError, AttributeError):
        return []


def build_profile(project_root: Path) -> dict[str, Any]:
    in_termux, termux_evidence = detect_termux()

    profile: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform_class": "TERMUX_ANDROID" if in_termux else "NOT_ANDROID",
        "termux_detection_evidence": termux_evidence,
        "os": {"system": platform.system(), "release": platform.release(), "python_version": platform.python_version()},
        "cpu": read_cpu_info(),
        "memory": read_memory_mb(),
        "storage": read_storage(project_root),
        "network_interfaces": read_network_interfaces(),
    }

    if in_termux:
        profile["android"] = read_android_properties()
        profile["battery"] = read_battery_status()
        profile["termux_shell_execution"] = True
        profile["git_available"] = shutil.which("git") is not None
        profile["python_available"] = shutil.which("python3") is not None
    else:
        profile["android"] = {"not_available_reason": "not running under Termux on Android -- see platform_class"}
        profile["battery"] = {"available": False, "not_available_reason": "not running under Termux on Android"}
        profile["termux_shell_execution"] = False
        profile["git_available"] = shutil.which("git") is not None  # still a real, honest check for THIS environment
        profile["python_available"] = shutil.which("python3") is not None

    existing_screenshots = project_root / "screenshots"
    profile["existing_forgeworld_mobile_research_files"] = {
        "project_root": str(project_root),
        "exists": project_root.exists(),
        "has_screenshots_dir": existing_screenshots.exists(),
        "screenshot_count": len(list(existing_screenshots.glob("*"))) if existing_screenshots.exists() else 0,
    }

    profile["device_classification"] = classify_device(profile)
    return profile


def classify_device(profile: dict[str, Any]) -> str:
    """Never guesses: returns UNKNOWN whenever the measurement it would
    need (RAM/storage) doesn't exist, rather than defaulting to a
    plausible-sounding tier."""
    if profile["platform_class"] != "TERMUX_ANDROID":
        return "UNKNOWN"

    ram_mb = profile["memory"].get("total_mb")
    storage_gb = profile["storage"].get("available_gb")
    battery = profile.get("battery", {})
    temp = battery.get("temperature") if battery.get("available") else None

    if ram_mb is None or storage_gb is None:
        return "UNKNOWN"
    if temp is not None and temp >= 42.0:
        return "THERMALLY_CONSTRAINED"
    if storage_gb < LOW_STORAGE_GB:
        return "STORAGE_CONSTRAINED"
    if ram_mb < LOW_RAM_MB:
        return "MEMORY_CONSTRAINED"
    if ram_mb >= HIGH_RAM_MB:
        return "PERFORMANCE"
    if ram_mb < HIGH_RAM_MB:
        return "BALANCED" if ram_mb >= LOW_RAM_MB else "LIGHT"
    return "UNKNOWN"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Discover this device and write MOBILE_DEVICE_PROFILE.json.")
    parser.add_argument("--out", default=None, help="Output path (default: <project_root>/MOBILE_DEVICE_PROFILE.json)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent
    out_path = Path(args.out) if args.out else project_root / "MOBILE_DEVICE_PROFILE.json"

    profile = build_profile(project_root)
    out_path.write_text(json.dumps(profile, indent=2))
    print(json.dumps(profile, indent=2))
    print(f"\nWritten to: {out_path}", flush=True)


if __name__ == "__main__":
    main()
