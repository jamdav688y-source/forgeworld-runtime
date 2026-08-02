"""ForgeWorld Cinema Player -- local Flask app.

Single process, binds to 127.0.0.1 only (matches the same privacy posture
as the earlier forgeworld-mobile-research project in this repo). Normal
playback (open the page, press play) requires no terminal, admin rights,
or internet connection once the process is running -- everything is
served from disk, `<video controls>` handles play/pause/seek/volume/
mute/fullscreen natively.
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, request, render_template, send_file, abort

CINEMA_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CINEMA_ROOT))

from alerts.engine import AlertEngine

RELEASE_DIR = CINEMA_ROOT / "RELEASES" / "FW-CINEMA-PLAYER-90S-V1"
MASTER_SPEC = json.loads((CINEMA_ROOT / "MASTER_SPEC.json").read_text())

app = Flask(__name__, template_folder="templates", static_folder="static")
_render_lock = threading.Lock()
alert_engine = AlertEngine(RELEASE_DIR / "ALERTS")


@app.route("/")
def index():
    return render_template("index.html", spec=MASTER_SPEC)


@app.route("/media/master/<aspect>")
def media_master(aspect: str):
    mapping = {"16x9": "MASTER/ForgeWorld_Cinema_Player_90s_1080p_24fps.mp4",
               "4x5": "SOCIAL/ForgeWorld_Cinema_Player_90s_LinkedIn_4x5_24fps.mp4"}
    if aspect not in mapping:
        abort(404)
    path = RELEASE_DIR / mapping[aspect]
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/media/preview/<aspect>")
def media_preview(aspect: str):
    mapping = {"16x9": "PREVIEW/FW_Cinema_Player_90s_16x9_preview.mp4",
               "4x5": "PREVIEW/FW_Cinema_Player_90s_4x5_preview.mp4"}
    if aspect not in mapping:
        abort(404)
    path = RELEASE_DIR / mapping[aspect]
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="video/mp4", conditional=True)


@app.route("/api/status")
def api_status():
    free_bytes = shutil.disk_usage(CINEMA_ROOT).free
    validation_dir = RELEASE_DIR / "VALIDATION"
    validation_status = "UNTESTED"
    if (validation_dir / "final_media_validation.json").exists():
        data = json.loads((validation_dir / "final_media_validation.json").read_text())
        validation_status = "PASS" if data.get("overall_pass") else "FAIL"

    masters_present = {
        "16x9": (RELEASE_DIR / "MASTER" / "ForgeWorld_Cinema_Player_90s_1080p_24fps.mp4").exists(),
        "4x5": (RELEASE_DIR / "SOCIAL" / "ForgeWorld_Cinema_Player_90s_LinkedIn_4x5_24fps.mp4").exists(),
    }

    return jsonify({
        "active_film": "FW-CINEMA-PLAYER-90S-V1",
        "target_fps": MASTER_SPEC["fps"]["num"],
        "resolutions": {k: f"{v['width']}x{v['height']}" for k, v in MASTER_SPEC["masters"].items()},
        "masters_present": masters_present,
        "render_in_progress": _render_lock.locked(),
        "validation_status": validation_status,
        "free_storage_bytes": free_bytes,
        "active_alerts": len(alert_engine.active_alerts()),
        "blocking_alerts": len(alert_engine.blocking_alerts()),
        "release_readiness": alert_engine.can_proceed_to_publish() and all(masters_present.values()),
    })


@app.route("/api/alerts")
def api_alerts():
    return jsonify([a.as_dict() for a in alert_engine.active_alerts()])


@app.route("/api/alerts/<alert_id>/acknowledge", methods=["POST"])
def api_ack_alert(alert_id: str):
    payload = request.get_json(silent=True) or {}
    by = payload.get("by", "operator")
    try:
        alert = alert_engine.acknowledge(alert_id, by=by)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(alert.as_dict())


@app.route("/api/alerts/<alert_id>/resolve", methods=["POST"])
def api_resolve_alert(alert_id: str):
    payload = request.get_json(silent=True) or {}
    evidence = payload.get("evidence", "")
    try:
        alert = alert_engine.resolve(alert_id, evidence=evidence)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(alert.as_dict())


@app.route("/api/validation_report")
def api_validation_report():
    path = RELEASE_DIR / "VALIDATION" / "final_media_validation.json"
    if not path.exists():
        return jsonify({"error": "no validation report yet"}), 404
    return jsonify(json.loads(path.read_text()))


@app.route("/api/release_folder")
def api_release_folder():
    """This container has no desktop file manager to 'open' -- the honest
    equivalent here is returning the absolute path plus a listing."""
    if not RELEASE_DIR.exists():
        return jsonify({"path": str(RELEASE_DIR), "exists": False, "entries": []})
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in RELEASE_DIR.iterdir())
    return jsonify({"path": str(RELEASE_DIR), "exists": True, "entries": entries})


@app.route("/api/artistic_review")
def api_artistic_review():
    path = RELEASE_DIR / "REVIEWS" / "artistic_review.md"
    if not path.exists():
        return jsonify({"error": "not written yet"}), 404
    return jsonify({"content": path.read_text()})


@app.route("/api/render/resume", methods=["POST"])
def api_render_resume():
    if not _render_lock.acquire(blocking=False):
        return jsonify({"error": "a render is already in progress"}), 409
    try:
        from renderer.render import render_aspect
        from renderer.profiles import get_profile
        aspect = (request.get_json(silent=True) or {}).get("aspect", "16x9")
        profile = get_profile(f"master_{aspect}")
        frames_dir = CINEMA_ROOT / "renderer" / "_frame_cache" / profile.aspect_key
        progress = render_aspect(profile.aspect_key, profile.width, profile.height, frames_dir)
        return jsonify(progress.as_dict())
    finally:
        _render_lock.release()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5099, debug=False)
