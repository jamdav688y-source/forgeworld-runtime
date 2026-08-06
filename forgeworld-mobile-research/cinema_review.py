"""Mobile Cinema Engine support: review records for AVAILABLE-tier mobile
Cinema capabilities (inspect frames/contact sheets/validation reports,
approve/reject, record feedback) -- never local heavy rendering, which is
DELEGATE_TO_WINDOWS per capability_negotiation/missions.py.

Reads real artifacts from the actual Cinema Player release built in this
repository (cinema/cinema_player_90s/RELEASES/) rather than a mock -- see
discover_cinema_artifacts().
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CINEMA_ROOT = REPO_ROOT / "cinema" / "cinema_player_90s"

APPROVAL_STATES = ("pending", "approved", "rejected", "needs_revision")
REVIEW_TYPES = (
    "scene_frame", "contact_sheet", "validation_report", "full_playback",
    "caption_review", "mobile_readability", "revision_comparison",
)

REQUIRED_FIELDS = [
    "artifact", "version", "device", "review_type", "observations",
    "defects", "approval_state", "operator_notes", "timestamp",
]


def discover_cinema_artifacts() -> list[dict[str, Any]]:
    """Real filesystem scan of cinema/cinema_player_90s/RELEASES/ -- what a
    mobile reviewer would actually have available to look at. Returns []
    (not fabricated entries) if no release exists yet."""
    releases_dir = CINEMA_ROOT / "RELEASES"
    if not releases_dir.exists():
        return []

    artifacts = []
    for release_dir in sorted(p for p in releases_dir.iterdir() if p.is_dir()):
        version = release_dir.name
        for sub, kind in [
            ("MASTER", "master_video"), ("SOCIAL", "social_video"),
            ("REVIEWS", "review_asset"), ("VALIDATION", "validation_report"),
        ]:
            sub_dir = release_dir / sub
            if not sub_dir.exists():
                continue
            for f in sorted(sub_dir.iterdir()):
                if f.is_file():
                    artifacts.append({
                        "artifact": f.name, "version": version, "kind": kind,
                        "path": str(f.relative_to(REPO_ROOT)), "size_bytes": f.stat().st_size,
                    })
    return artifacts


def read_validation_summary(version: str) -> dict[str, Any] | None:
    """Surfaces the REAL validation result from the actual Cinema Player
    build for mobile review, rather than re-deriving or guessing it."""
    path = CINEMA_ROOT / "RELEASES" / version / "VALIDATION" / "final_media_validation.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def create_review(
    artifact: str, version: str, device: str, review_type: str,
    observations: list[str] | None = None, defects: list[str] | None = None,
    approval_state: str = "pending", operator_notes: str = "",
) -> dict[str, Any]:
    if review_type not in REVIEW_TYPES:
        raise ValueError(f"review_type must be one of {REVIEW_TYPES}, got {review_type!r}")
    if approval_state not in APPROVAL_STATES:
        raise ValueError(f"approval_state must be one of {APPROVAL_STATES}, got {approval_state!r}")

    return {
        "artifact": artifact,
        "version": version,
        "device": device,
        "review_type": review_type,
        "observations": observations or [],
        "defects": defects or [],
        "approval_state": approval_state,
        "operator_notes": operator_notes,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def validate_review(review: dict[str, Any]) -> list[str]:
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in review:
            errors.append(f"missing required field '{field}'")
    if "approval_state" in review and review["approval_state"] not in APPROVAL_STATES:
        errors.append(f"approval_state '{review['approval_state']}' not one of {APPROVAL_STATES}")
    if "review_type" in review and review["review_type"] not in REVIEW_TYPES:
        errors.append(f"review_type '{review['review_type']}' not one of {REVIEW_TYPES}")
    if "artifact" in review and not str(review["artifact"]).strip():
        errors.append("artifact must be a non-empty string")
    return errors


def _review_id(review: dict[str, Any]) -> str:
    safe_artifact = review["artifact"].replace("/", "_").replace(" ", "_")
    return f"{review['version']}__{safe_artifact}__{review['timestamp'].replace(':', '')}"


def save_review(review: dict[str, Any], evidence_dir: Path) -> Path:
    errors = validate_review(review)
    if errors:
        raise ValueError(f"cannot save invalid review: {errors}")
    evidence_dir.mkdir(parents=True, exist_ok=True)
    out_path = evidence_dir / f"{_review_id(review)}.json"
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(review, indent=2))
    tmp.replace(out_path)
    return out_path


def list_reviews(evidence_dir: Path) -> list[dict[str, Any]]:
    if not evidence_dir.exists():
        return []
    reviews = []
    for path in sorted(evidence_dir.glob("*.json")):
        try:
            reviews.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return reviews


def review_queue_summary(evidence_dir: Path) -> dict[str, int]:
    reviews = list_reviews(evidence_dir)
    summary = {state: 0 for state in APPROVAL_STATES}
    for r in reviews:
        summary[r.get("approval_state", "pending")] = summary.get(r.get("approval_state", "pending"), 0) + 1
    summary["total"] = len(reviews)
    return summary
