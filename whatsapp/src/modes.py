"""Operating-mode state machine (mission Section 5).

Mode state lives in a single JSON file, not in memory, so a phone-issued
EMERGENCY_STOP takes effect on the very next call regardless of which
process is running the pipeline.

Functions resolve `modes.CONFIG_PATH` at call time (via `None` sentinel
defaults) rather than binding a default argument at definition time, so
tests can monkeypatch `modes.CONFIG_PATH` and have every function pick up
the override -- a plain `path: Path = CONFIG_PATH` default would freeze the
original value at import time and silently ignore the monkeypatch.
"""
import json
from pathlib import Path

MODULE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = MODULE_ROOT / "config.json"

VALID_INBOUND = {"ENABLED_AFTER_VERIFICATION", "DISABLED"}
VALID_OUTBOUND = {"DRAFT_ONLY", "ASSIST_LOW_RISK", "EMERGENCY_STOP"}
VALID_CAMPAIGN = {"DISABLED", "ENABLED"}


def load_config(path: Path = None) -> dict:
    path = path if path is not None else CONFIG_PATH
    with open(path) as f:
        return json.load(f)


def save_config(config: dict, path: Path = None) -> None:
    path = path if path is not None else CONFIG_PATH
    with open(path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


def get_mode(path: Path = None) -> dict:
    return load_config(path)["mode"]


def emergency_stop(path: Path = None) -> dict:
    """Immediately disable outbound delivery. Inbound recording continues."""
    config = load_config(path)
    config["mode"]["outbound"] = "EMERGENCY_STOP"
    save_config(config, path)
    return config["mode"]


def resume_draft_mode(path: Path = None) -> dict:
    """Explicit, deliberate action to leave EMERGENCY_STOP. Never automatic."""
    config = load_config(path)
    config["mode"]["outbound"] = "DRAFT_ONLY"
    save_config(config, path)
    return config["mode"]


def is_outbound_blocked(path: Path = None) -> bool:
    return get_mode(path)["outbound"] == "EMERGENCY_STOP"
