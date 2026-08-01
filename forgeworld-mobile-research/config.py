"""Configuration loading for the ForgeWorld Mobile Research Companion.

Plain dataclasses + JSON files. No Pydantic (pydantic-core fails to
compile under Termux/Android via Rust+Maturin).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
RUNTIME_DIR = PROJECT_ROOT / "runtime"

SETTINGS_PATH = CONFIG_DIR / "settings.json"
SOURCE_PATHS_PATH = CONFIG_DIR / "source_paths.json"
CLASSIFICATION_RULES_PATH = CONFIG_DIR / "classification_rules.json"
PROMPT_TEMPLATES_PATH = CONFIG_DIR / "prompt_templates.json"

SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

CANDIDATE_SCREENSHOT_DIRS = [
    "~/storage/shared/DCIM/Screenshots",
    "~/storage/shared/Pictures/Screenshots",
    "~/storage/shared/Screenshots",
    "/storage/emulated/0/DCIM/Screenshots",
    "/storage/emulated/0/Pictures/Screenshots",
    "/storage/emulated/0/Screenshots",
]


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=False)
        fh.write("\n")
    tmp_path.replace(path)


@dataclass
class Settings:
    application_name: str = "ForgeWorld Mobile Research Companion"
    host: str = "127.0.0.1"
    port: int = 5055
    debug: bool = False
    database_path: str = "runtime/database/forgeworld_research.db"
    sqlite_wal: bool = True
    sqlite_busy_timeout_ms: int = 5000
    manual_scan_default: bool = True
    max_initial_batch: int = 5
    max_normal_batch: int = 25
    max_preview_dimension: int = 1280
    max_ocr_dimension: int = 2200
    ocr_jobs_parallel: int = 1
    ocr_language: str = "eng"
    ocr_timeout_seconds: int = 45
    preserve_originals: bool = True
    skip_existing_hashes: bool = True
    cloud_uploads_enabled: bool = False
    execute_ocr_text: bool = False
    semantic_search_enabled: bool = False
    bounded_polling_enabled: bool = False
    bounded_polling_interval_seconds: int = 300
    scheduled_scan_enabled: bool = False

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "Settings":
        if not path.exists():
            settings = cls()
            _write_json(path, asdict(settings))
            return settings
        data = _read_json(path)
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)

    def save(self, path: Path = SETTINGS_PATH) -> None:
        _write_json(path, asdict(self))

    def database_full_path(self) -> Path:
        p = Path(self.database_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p


@dataclass
class SourceLocation:
    path: str
    label: str
    enabled: bool = False

    def expanded_path(self) -> Path:
        return Path(self.path).expanduser()

    def exists(self) -> bool:
        try:
            return self.expanded_path().is_dir()
        except OSError:
            return False


def load_source_paths(path: Path = SOURCE_PATHS_PATH) -> list[SourceLocation]:
    if not path.exists():
        seed = {
            "sources": [
                {"path": p, "label": Path(p).name or p, "enabled": False}
                for p in CANDIDATE_SCREENSHOT_DIRS
            ]
        }
        _write_json(path, seed)
        data = seed
    else:
        data = _read_json(path)
    return [SourceLocation(**s) for s in data.get("sources", [])]


def save_source_paths(sources: list[SourceLocation], path: Path = SOURCE_PATHS_PATH) -> None:
    _write_json(path, {"sources": [asdict(s) for s in sources]})


def probe_source_paths(path: Path = SOURCE_PATHS_PATH) -> list[SourceLocation]:
    """Re-check every known candidate directory and enable only those that exist.

    Also runs a bounded (maxdepth 5) search under ~/storage/shared for any
    directory whose name contains 'screenshot', adding newly discovered
    paths as disabled-by-default entries for the operator to review.
    """
    sources = load_source_paths(path)
    by_path = {s.path: s for s in sources}

    for candidate in CANDIDATE_SCREENSHOT_DIRS:
        loc = by_path.get(candidate)
        if loc is None:
            loc = SourceLocation(path=candidate, label=Path(candidate).name or candidate, enabled=False)
            sources.append(loc)
            by_path[candidate] = loc
        loc.enabled = loc.exists()

    shared_root = Path("~/storage/shared").expanduser()
    if shared_root.is_dir():
        found = _bounded_screenshot_dir_search(shared_root, max_depth=5)
        for discovered in found:
            key = str(discovered)
            if key not in by_path:
                loc = SourceLocation(path=key, label=discovered.name, enabled=False)
                sources.append(loc)
                by_path[key] = loc

    save_source_paths(sources, path)
    return sources


def _bounded_screenshot_dir_search(root: Path, max_depth: int) -> list[Path]:
    results: list[Path] = []
    root_depth = len(root.parts)
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            depth = len(entry.parts) - root_depth
            if "screenshot" in entry.name.lower():
                results.append(entry)
            if depth < max_depth:
                stack.append(entry)
    return results


def enabled_source_paths(path: Path = SOURCE_PATHS_PATH) -> list[SourceLocation]:
    return [s for s in load_source_paths(path) if s.enabled and s.exists()]


def load_classification_rules(path: Path = CLASSIFICATION_RULES_PATH) -> dict[str, Any]:
    return _read_json(path)


def load_prompt_templates(path: Path = PROMPT_TEMPLATES_PATH) -> dict[str, Any]:
    return _read_json(path)


def ensure_runtime_dirs() -> None:
    for sub in ("database", "backups", "cache", "previews", "ocr", "logs", "exports", "tmp"):
        (RUNTIME_DIR / sub).mkdir(parents=True, exist_ok=True)
