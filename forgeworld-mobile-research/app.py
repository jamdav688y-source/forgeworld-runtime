"""ForgeWorld Mobile Research Companion -- single Flask application.

One process, one SQLite database, one browser shell (templates/index.html)
that drives every tab (Dashboard/Library/Search/Collections/Prompt Lab/
Ingestion/Settings/System Status) through this JSON API. Binds to
127.0.0.1 only by default -- never 0.0.0.0.
"""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import shutil
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, render_template, send_file, abort
from werkzeug.exceptions import HTTPException

import config as cfg
from config import Settings, SourceLocation
from database import Database, open_database, utcnow
from indexer import scan as run_scan, STATUS_PROCESSED
from ocr import run_ocr, OCR_STATE_CORRECTED, OCR_STATE_UNUSABLE, VALID_OCR_STATES
from search import SearchFilters, search_screenshots
from prompts import VALID_MODES, build_source_inventory, render_prompt, save_generated_prompt, save_prompt_template
from summarizer import build_labeled_summary
from watcher import BoundedPoller
from integrations import get_integration_adapters

PROJECT_ROOT = cfg.PROJECT_ROOT

log = cfg.configure_logging()
app_log = log.getChild("app")

app = Flask(__name__, template_folder="templates", static_folder="static")

_state: dict = {}
_scan_lock = threading.Lock()


def init_app_state() -> None:
    cfg.ensure_runtime_dirs()
    settings = Settings.load()
    db = open_database(settings, PROJECT_ROOT)
    _state["settings"] = settings
    _state["db"] = db
    _state["last_scan"] = None
    _state["poller"] = BoundedPoller(db, settings, cfg.enabled_source_paths, PROJECT_ROOT)
    if settings.bounded_polling_enabled:
        try:
            _state["poller"].start()
            app_log.info("bounded polling started at startup (interval=%ss)", settings.bounded_polling_interval_seconds)
        except Exception:
            app_log.exception("failed to start bounded polling at startup")


def get_db() -> Database:
    return _state["db"]


def get_settings() -> Settings:
    return _state["settings"]


def get_poller() -> BoundedPoller:
    return _state["poller"]


# --------------------------------------------------------- error handling -

@app.errorhandler(ValueError)
@app.errorhandler(TypeError)
def handle_bad_input(e):
    app_log.warning("bad input on %s: %s", request.path, e)
    return jsonify({"error": str(e)}), 400


@app.errorhandler(HTTPException)
def handle_http_exception(e):
    response = jsonify({"error": e.description, "code": e.code})
    response.status_code = e.code
    return response


@app.errorhandler(Exception)
def handle_unexpected_exception(e):
    app_log.exception("unhandled exception on %s", request.path)
    return jsonify({"error": "internal error", "detail": str(e)}), 500


# ---------------------------------------------------------------- shell ---

@app.route("/")
def index():
    return render_template("index.html", app_name=get_settings().application_name)


# ------------------------------------------------------------ dashboard ---

@app.route("/api/dashboard")
def api_dashboard():
    db = get_db()
    total = db.query_one("SELECT COUNT(*) c FROM screenshots")["c"]
    processed = db.query_one("SELECT COUNT(*) c FROM screenshots WHERE processing_status = 'PROCESSED'")["c"]
    pending = db.query_one("SELECT COUNT(*) c FROM screenshots WHERE processing_status = 'PENDING'")["c"]
    failed = db.query_one("SELECT COUNT(*) c FROM screenshots WHERE processing_status = 'FAILED'")["c"]
    ocr_failures = db.query_one(
        "SELECT COUNT(DISTINCT screenshot_id) c FROM ocr_extractions WHERE success_state IN ('FAILED','TIMEOUT')"
    )["c"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_today = db.query_one(
        "SELECT COUNT(*) c FROM screenshots WHERE discovered_at LIKE ?", (f"{today}%",)
    )["c"]
    top_topics = db.query(
        """SELECT t.name, COUNT(*) c FROM screenshot_tags st JOIN tags t ON t.id = st.tag_id
           WHERE t.name != 'unknown' GROUP BY t.name ORDER BY c DESC LIMIT 8"""
    )
    top_entities = db.query(
        """SELECT e.name, e.entity_type, COUNT(*) c FROM screenshot_entities se JOIN entities e ON e.id = se.entity_id
           GROUP BY e.name, e.entity_type ORDER BY c DESC LIMIT 8"""
    )
    recent_collections = db.query("SELECT id, name, updated_at FROM collections ORDER BY updated_at DESC LIMIT 5")
    last_event = db.query_one(
        "SELECT message, created_at FROM processing_events WHERE event_type = 'SCAN_COMPLETE' ORDER BY id DESC LIMIT 1"
    )
    free_bytes = shutil.disk_usage(PROJECT_ROOT).free

    return jsonify({
        "total_screenshots": total,
        "processed_screenshots": processed,
        "pending_screenshots": pending,
        "failed_screenshots": failed,
        "ocr_failures": ocr_failures,
        "new_today": new_today,
        "top_topics": [dict(r) for r in top_topics],
        "top_entities": [dict(r) for r in top_entities],
        "recent_collections": [dict(r) for r in recent_collections],
        "last_scan": dict(last_event) if last_event else None,
        "database_size_bytes": db.database_size_bytes(),
        "free_storage_bytes": free_bytes,
    })


# --------------------------------------------------------------- library --

@app.route("/api/library")
def api_library():
    db = get_db()
    limit = int(request.args.get("limit", 30))
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status")
    where = []
    params: list = []
    if status:
        where.append("processing_status = ?")
        params.append(status)
    sql = "SELECT id, filename, title, content_type, processing_status, discovered_at, sha256, classification_confidence FROM screenshots"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY discovered_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = db.query(sql, tuple(params))
    items = []
    for r in rows:
        d = dict(r)
        d["preview_path"] = f"/previews/{d['sha256']}.jpg"
        items.append(d)
    total = db.query_one("SELECT COUNT(*) c FROM screenshots")["c"]
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


@app.route("/api/screenshots/<int:screenshot_id>")
def api_screenshot_detail(screenshot_id: int):
    db = get_db()
    row = db.query_one("SELECT * FROM screenshots WHERE id = ?", (screenshot_id,))
    if row is None:
        abort(404)
    data = dict(row)
    data["preview_path"] = f"/previews/{data['sha256']}.jpg"
    data["original_url"] = f"/originals/{screenshot_id}"

    data["tags"] = [dict(r) for r in db.query(
        """SELECT t.name, st.confidence, st.rationale, st.rule_id, st.operator_assigned
           FROM screenshot_tags st JOIN tags t ON t.id = st.tag_id WHERE st.screenshot_id = ?""",
        (screenshot_id,),
    )]
    data["entities"] = [dict(r) for r in db.query(
        """SELECT e.name, e.entity_type, se.confidence, se.rationale, se.rule_id
           FROM screenshot_entities se JOIN entities e ON e.id = se.entity_id WHERE se.screenshot_id = ?""",
        (screenshot_id,),
    )]
    data["notes"] = [dict(r) for r in db.query(
        "SELECT id, body, author, created_at, updated_at FROM notes WHERE screenshot_id = ? ORDER BY created_at ASC",
        (screenshot_id,),
    )]
    data["ocr_extractions"] = [dict(r) for r in db.query(
        "SELECT * FROM ocr_extractions WHERE screenshot_id = ? ORDER BY id DESC", (screenshot_id,)
    )]
    data["ocr_revisions"] = [dict(r) for r in db.query(
        "SELECT * FROM ocr_revisions WHERE screenshot_id = ? ORDER BY id DESC", (screenshot_id,)
    )]
    data["processing_events"] = [dict(r) for r in db.query(
        "SELECT event_type, message, created_at FROM processing_events WHERE screenshot_id = ? ORDER BY id ASC",
        (screenshot_id,),
    )]
    data["collections"] = [dict(r) for r in db.query(
        """SELECT c.id, c.name FROM collections c JOIN collection_items ci ON ci.collection_id = c.id
           WHERE ci.screenshot_id = ?""",
        (screenshot_id,),
    )]
    return jsonify(data)


@app.route("/previews/<path:filename>")
def serve_preview(filename: str):
    previews_dir = PROJECT_ROOT / "runtime" / "previews"
    safe_name = Path(filename).name
    target = previews_dir / safe_name
    if not target.resolve().is_relative_to(previews_dir.resolve()) or not target.exists():
        abort(404)
    return send_file(target)


@app.route("/originals/<int:screenshot_id>")
def serve_original(screenshot_id: int):
    row = get_db().query_one("SELECT original_path FROM screenshots WHERE id = ?", (screenshot_id,))
    if row is None:
        abort(404)
    path = Path(row["original_path"])
    if not path.is_file():
        abort(404)
    return send_file(path)


# ------------------------------------------------------------------ notes -

@app.route("/api/screenshots/<int:screenshot_id>/notes", methods=["POST"])
def api_add_note(screenshot_id: int):
    db = get_db()
    payload = request.get_json(force=True) or {}
    body = payload.get("body", "").strip()
    author = payload.get("author")
    if not body:
        return jsonify({"error": "body is required"}), 400
    now = utcnow()
    cur = db.execute(
        "INSERT INTO notes (screenshot_id, body, author, created_at, updated_at) VALUES (?,?,?,?,?)",
        (screenshot_id, body, author, now, now),
    )
    db.record_event(screenshot_id, "NOTE_ADDED", "")
    return jsonify({"id": cur.lastrowid, "created_at": now})


@app.route("/api/notes/<int:note_id>", methods=["PUT"])
def api_update_note(note_id: int):
    db = get_db()
    body = (request.get_json(force=True) or {}).get("body", "").strip()
    if not body:
        return jsonify({"error": "body is required"}), 400
    db.execute("UPDATE notes SET body = ?, updated_at = ? WHERE id = ?", (body, utcnow(), note_id))
    return jsonify({"ok": True})


# -------------------------------------------------------------------- ocr -

@app.route("/api/screenshots/<int:screenshot_id>/ocr/rerun", methods=["POST"])
def api_rerun_ocr(screenshot_id: int):
    db = get_db()
    settings = get_settings()
    row = db.query_one("SELECT original_path FROM screenshots WHERE id = ?", (screenshot_id,))
    if row is None:
        abort(404)
    result = run_ocr(
        Path(row["original_path"]),
        language=settings.ocr_language,
        timeout_seconds=settings.ocr_timeout_seconds,
        max_dimension=settings.max_ocr_dimension,
    )
    db.execute(
        """INSERT INTO ocr_extractions (
            screenshot_id, raw_text, normalized_text, engine_name, engine_version, language,
            extracted_at, success_state, warnings, errors, confidence, duration_ms
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (screenshot_id, result.raw_text, result.normalized_text, result.engine_name, result.engine_version,
         result.language, result.extracted_at, result.success_state, "; ".join(result.warnings),
         "; ".join(result.errors), result.confidence, result.duration_ms),
    )
    summary = build_labeled_summary(result.normalized_text) if result.normalized_text else ""
    db.execute(
        "UPDATE screenshots SET raw_ocr_text = ?, ocr_confidence = ?, summary = ?, updated_at = ? WHERE id = ?",
        (result.normalized_text, result.confidence, summary, utcnow(), screenshot_id),
    )
    db.record_event(screenshot_id, "OCR_RERUN", f"state={result.success_state}")
    app_log.info("OCR rerun for screenshot %s -> %s", screenshot_id, result.success_state)
    return jsonify({"success_state": result.success_state, "normalized_text": result.normalized_text})


@app.route("/api/screenshots/<int:screenshot_id>/ocr/correct", methods=["POST"])
def api_correct_ocr(screenshot_id: int):
    db = get_db()
    payload = request.get_json(force=True) or {}
    corrected_text = payload.get("corrected_text", "").strip()
    note = payload.get("revision_note", "")
    if not corrected_text:
        return jsonify({"error": "corrected_text is required"}), 400
    row = db.query_one("SELECT corrected_ocr_text FROM screenshots WHERE id = ?", (screenshot_id,))
    if row is None:
        abort(404)
    db.execute(
        "INSERT INTO ocr_revisions (screenshot_id, previous_text, corrected_text, revision_note, created_at) VALUES (?,?,?,?,?)",
        (screenshot_id, row["corrected_ocr_text"], corrected_text, note, utcnow()),
    )
    db.execute(
        "UPDATE screenshots SET corrected_ocr_text = ?, updated_at = ? WHERE id = ?",
        (corrected_text, utcnow(), screenshot_id),
    )
    db.record_event(screenshot_id, "OCR_CORRECTED", note)
    app_log.info("OCR correction saved for screenshot %s", screenshot_id)
    return jsonify({"ok": True})


@app.route("/api/screenshots/<int:screenshot_id>/ocr/unusable", methods=["POST"])
def api_mark_unusable(screenshot_id: int):
    db = get_db()
    row = db.query_one("SELECT id FROM screenshots WHERE id = ?", (screenshot_id,))
    if row is None:
        abort(404)
    db.execute(
        "INSERT INTO ocr_extractions (screenshot_id, engine_name, language, extracted_at, success_state) VALUES (?,?,?,?,?)",
        (screenshot_id, "operator", get_settings().ocr_language, utcnow(), OCR_STATE_UNUSABLE),
    )
    db.record_event(screenshot_id, "OCR_MARKED_UNUSABLE", "")
    return jsonify({"ok": True})


# ----------------------------------------------------------------- search -

@app.route("/api/search")
def api_search():
    db = get_db()
    filters = SearchFilters(
        keywords=request.args.get("q", ""),
        tags=[t for t in request.args.get("tags", "").split(",") if t],
        platforms=[p for p in request.args.get("platforms", "").split(",") if p],
        content_types=[c for c in request.args.get("content_types", "").split(",") if c],
        date_from=request.args.get("date_from") or None,
        date_to=request.args.get("date_to") or None,
        collection_id=int(request.args["collection_id"]) if request.args.get("collection_id") else None,
        min_confidence=float(request.args["min_confidence"]) if request.args.get("min_confidence") else None,
        sort=request.args.get("sort", "relevance"),
        limit=int(request.args.get("limit", 25)),
        offset=int(request.args.get("offset", 0)),
    )
    results = search_screenshots(db, filters)
    return jsonify({"results": results, "count": len(results)})


# ------------------------------------------------------------- collections -

@app.route("/api/collections", methods=["GET", "POST"])
def api_collections():
    db = get_db()
    if request.method == "POST":
        name = (request.get_json(force=True) or {}).get("name", "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        now = utcnow()
        try:
            cur = db.execute(
                "INSERT INTO collections (name, created_at, updated_at) VALUES (?,?,?)", (name, now, now)
            )
        except Exception:
            return jsonify({"error": "a collection with this name already exists"}), 409
        return jsonify({"id": cur.lastrowid, "name": name})
    rows = db.query(
        """SELECT c.id, c.name, c.created_at, c.updated_at, COUNT(ci.screenshot_id) item_count
           FROM collections c LEFT JOIN collection_items ci ON ci.collection_id = c.id
           GROUP BY c.id ORDER BY c.updated_at DESC"""
    )
    return jsonify([dict(r) for r in rows])


@app.route("/api/collections/<int:collection_id>", methods=["GET", "PUT"])
def api_collection_detail(collection_id: int):
    db = get_db()
    if request.method == "PUT":
        name = (request.get_json(force=True) or {}).get("name", "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        db.execute("UPDATE collections SET name = ?, updated_at = ? WHERE id = ?", (name, utcnow(), collection_id))
        return jsonify({"ok": True})
    row = db.query_one("SELECT * FROM collections WHERE id = ?", (collection_id,))
    if row is None:
        abort(404)
    items = db.query(
        """SELECT s.id, s.filename, s.title, s.sha256, s.content_type, s.processing_status
           FROM collection_items ci JOIN screenshots s ON s.id = ci.screenshot_id
           WHERE ci.collection_id = ? ORDER BY ci.added_at DESC""",
        (collection_id,),
    )
    data = dict(row)
    data["items"] = [dict(i) for i in items]
    return jsonify(data)


@app.route("/api/collections/<int:collection_id>/items", methods=["POST"])
def api_collection_items(collection_id: int):
    db = get_db()
    payload = request.get_json(force=True) or {}
    action = payload.get("action", "add")
    screenshot_ids = payload.get("screenshot_ids", [])
    now = utcnow()
    if action == "add":
        for sid in screenshot_ids:
            db.execute(
                "INSERT OR IGNORE INTO collection_items (collection_id, screenshot_id, added_at) VALUES (?,?,?)",
                (collection_id, sid, now),
            )
    elif action == "remove":
        for sid in screenshot_ids:
            db.execute(
                "DELETE FROM collection_items WHERE collection_id = ? AND screenshot_id = ?", (collection_id, sid)
            )
    else:
        return jsonify({"error": "action must be 'add' or 'remove'"}), 400
    db.execute("UPDATE collections SET updated_at = ? WHERE id = ?", (now, collection_id))
    return jsonify({"ok": True})


# ---------------------------------------------------------------- sources -

@app.route("/api/sources", methods=["GET", "POST"])
def api_sources():
    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        path = payload.get("path", "").strip()
        label = payload.get("label", "").strip() or path
        if not path:
            return jsonify({"error": "path is required"}), 400
        sources = cfg.load_source_paths()
        sources.append(SourceLocation(path=path, label=label, enabled=Path(path).expanduser().is_dir()))
        cfg.save_source_paths(sources)
        return jsonify({"ok": True})
    sources = cfg.load_source_paths()
    return jsonify([{**asdict(s), "exists": s.exists()} for s in sources])


@app.route("/api/sources/update", methods=["POST"])
def api_update_source():
    payload = request.get_json(force=True) or {}
    source_path = payload.get("path", "")
    sources = cfg.load_source_paths()
    found = False
    for s in sources:
        if s.path == source_path:
            if "enabled" in payload:
                s.enabled = bool(payload["enabled"])
            if "label" in payload:
                s.label = payload["label"]
            found = True
    if not found:
        return jsonify({"error": "source not found"}), 404
    cfg.save_source_paths(sources)
    return jsonify({"ok": True})


@app.route("/api/sources/probe", methods=["POST"])
def api_probe_sources():
    sources = cfg.probe_source_paths()
    return jsonify([{**asdict(s), "exists": s.exists()} for s in sources])


# ------------------------------------------------------------------- scan -

@app.route("/api/scan", methods=["POST"])
def api_scan():
    db = get_db()
    settings = get_settings()
    payload = request.get_json(silent=True) or {}
    batch_limit = payload.get("batch_limit", settings.max_normal_batch)
    try:
        batch_limit = int(batch_limit)
    except (TypeError, ValueError):
        return jsonify({"error": "batch_limit must be an integer"}), 400

    if not _scan_lock.acquire(blocking=False):
        app_log.info("scan request rejected: a scan is already in progress")
        return jsonify({"error": "a scan is already in progress"}), 409

    try:
        sources = cfg.enabled_source_paths()
        if not sources:
            return jsonify({"error": "no enabled + existing source directories. Probe sources first."}), 400

        app_log.info("scan starting: sources=%s batch_limit=%s", [s.path for s in sources], batch_limit)
        summary = run_scan(db, settings, sources, PROJECT_ROOT, batch_limit=batch_limit)
    finally:
        _scan_lock.release()

    _state["last_scan"] = asdict(summary) | {"outcomes": [asdict(o) for o in summary.outcomes]}
    app_log.info(
        "scan finished: new=%s resumed=%s dup=%s skipped=%s errors=%s",
        summary.new_count, summary.resumed_count, summary.duplicate_count,
        summary.skipped_count, summary.error_count,
    )
    return jsonify(_state["last_scan"])


@app.route("/api/scan/last")
def api_scan_last():
    return jsonify(_state.get("last_scan"))


@app.route("/api/scan/status")
def api_scan_status():
    return jsonify({"scan_in_progress": _scan_lock.locked()})


# --------------------------------------------------------------- settings -

_SETTINGS_FIELD_TYPES = {f.name: f.type for f in dataclasses.fields(Settings)}


def _coerce_setting_value(key: str, value):
    """Best-effort type coercion so a stray string from a form field
    ('5' for max_normal_batch) doesn't silently store the wrong type, and
    an outright invalid value (e.g. a non-numeric port) is rejected with a
    clear error instead of corrupting settings.json."""
    declared_type = _SETTINGS_FIELD_TYPES.get(key)
    if declared_type in ("int", int):
        return int(value)
    if declared_type in ("float", float):
        return float(value)
    if declared_type in ("bool", bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    return value


@app.route("/api/settings", methods=["GET", "PUT"])
def api_settings():
    if request.method == "PUT":
        payload = request.get_json(force=True) or {}
        settings = get_settings()
        rejected = {}
        for key, value in payload.items():
            if not hasattr(settings, key):
                continue
            try:
                setattr(settings, key, _coerce_setting_value(key, value))
            except (TypeError, ValueError) as exc:
                rejected[key] = str(exc)
        if rejected:
            return jsonify({"error": "some settings were invalid and not applied", "rejected": rejected}), 400
        settings.save()
        app_log.info("settings updated: %s", list(payload.keys()))
        _sync_poller_with_settings()
        return jsonify(asdict(settings))
    return jsonify(asdict(get_settings()))


def _sync_poller_with_settings() -> None:
    settings = get_settings()
    poller = get_poller()
    if settings.bounded_polling_enabled and not poller.running:
        poller.start()
        app_log.info("bounded polling started via settings update")
    elif not settings.bounded_polling_enabled and poller.running:
        poller.stop()
        app_log.info("bounded polling stopped via settings update")


@app.route("/api/polling/start", methods=["POST"])
def api_polling_start():
    settings = get_settings()
    if not settings.bounded_polling_enabled:
        return jsonify({"error": "bounded_polling_enabled is false in settings"}), 400
    get_poller().start()
    return jsonify({"running": get_poller().running})


@app.route("/api/polling/stop", methods=["POST"])
def api_polling_stop():
    get_poller().stop()
    return jsonify({"running": get_poller().running})


@app.route("/api/system_status")
def api_system_status():
    db = get_db()
    settings = get_settings()
    free_bytes = shutil.disk_usage(PROJECT_ROOT).free
    return jsonify({
        "application_name": settings.application_name,
        "host": settings.host,
        "port": settings.port,
        "database_path": str(settings.database_full_path()),
        "database_size_bytes": db.database_size_bytes(),
        "free_storage_bytes": free_bytes,
        "semantic_search_enabled": settings.semantic_search_enabled,
        "bounded_polling_enabled": settings.bounded_polling_enabled,
        "bounded_polling_running": get_poller().running,
        "cloud_uploads_enabled": settings.cloud_uploads_enabled,
        "scan_in_progress": _scan_lock.locked(),
        "forgeworld_integrations": {
            key: adapter.describe() for key, adapter in get_integration_adapters().items()
        },
    })


# --------------------------------------------------------------- prompts --

@app.route("/api/prompt_modes")
def api_prompt_modes():
    templates = cfg.load_prompt_templates()
    return jsonify(templates.get("modes", {}))


@app.route("/api/prompts/generate", methods=["POST"])
def api_generate_prompt():
    db = get_db()
    payload = request.get_json(force=True) or {}
    mode = payload.get("mode")
    objective = payload.get("objective", "")
    screenshot_ids = payload.get("screenshot_ids", [])
    operator_instruction = payload.get("operator_instruction", "")
    if mode not in VALID_MODES:
        return jsonify({"error": f"mode must be one of {VALID_MODES}"}), 400
    if not screenshot_ids:
        return jsonify({"error": "screenshot_ids must be non-empty"}), 400
    inventory = build_source_inventory(db, screenshot_ids)
    content = render_prompt(mode, objective, inventory, operator_instruction)
    prompt_id = save_generated_prompt(db, mode, objective, screenshot_ids, content)
    return jsonify({"id": prompt_id, "content": content})


@app.route("/api/prompts/<int:prompt_id>/save_template", methods=["POST"])
def api_save_prompt_template(prompt_id: int):
    db = get_db()
    payload = request.get_json(force=True) or {}
    name = payload.get("name", "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    row = db.query_one("SELECT mode, content FROM generated_prompts WHERE id = ?", (prompt_id,))
    if row is None:
        abort(404)
    template_id = save_prompt_template(db, row["mode"], name, row["content"])
    return jsonify({"id": template_id})


# --------------------------------------------------------------- exports --

def _export_screenshot_ids(request_args) -> list[int]:
    if request_args.get("collection_id"):
        db = get_db()
        rows = db.query(
            "SELECT screenshot_id FROM collection_items WHERE collection_id = ?",
            (int(request_args["collection_id"]),),
        )
        return [r["screenshot_id"] for r in rows]
    raw = request_args.get("screenshot_ids", "")
    return [int(x) for x in raw.split(",") if x]


def _write_export(filename: str, content: str | bytes, binary: bool = False) -> Path:
    exports_dir = PROJECT_ROOT / "runtime" / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    dest = exports_dir / filename
    mode = "wb" if binary else "w"
    with dest.open(mode, encoding=None if binary else "utf-8") as fh:
        fh.write(content)
    return dest


@app.route("/api/exports/<kind>")
def api_export(kind: str):
    db = get_db()
    screenshot_ids = _export_screenshot_ids(request.args)
    if not screenshot_ids:
        return jsonify({"error": "no screenshots selected (pass screenshot_ids or collection_id)"}), 400
    inventory = build_source_inventory(db, screenshot_ids)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    prompt_mode_by_kind = {
        "notebooklm": "CREATE_NOTEBOOKLM_SOURCE_BRIEF",
        "codex": "CREATE_CODEX_DIRECTIVE",
        "claude_code": "CREATE_CLAUDE_CODE_DIRECTIVE",
        "cinema": "CREATE_CINEMA_BRIEF",
        "rpg": "CREATE_RPG_MECHANIC",
    }

    if kind == "markdown":
        lines = [f"# ForgeWorld Research Brief", f"export_timestamp: {utcnow()}", ""]
        for item in inventory:
            lines += [
                f"## Source {item.screenshot_id}",
                f"- sha256: {item.sha256}",
                f"- original_path: {item.original_path}",
                f"- processing_status: {item.processing_status}",
                f"- raw OCR: {item.ocr_excerpt or '(none)'}",
                f"- corrected OCR: {item.corrected_ocr_excerpt or '(none)'}",
                f"- tags: {', '.join(item.tags) or 'UNKNOWN'}",
                f"- entities: {', '.join(item.entities) or 'UNKNOWN'}",
                f"- system summary: {item.system_summary or 'UNKNOWN'}",
                f"- operator notes: {'; '.join(item.operator_notes) or '(none)'}",
                f"- uncertainty: {'; '.join(item.uncertainty) or 'none flagged'}",
                "",
            ]
        content = "\n".join(lines)
        dest = _write_export(f"research_brief_{stamp}.md", content)
        return jsonify({"path": str(dest.relative_to(PROJECT_ROOT)), "content": content})

    if kind == "json":
        payload = {"export_timestamp": utcnow(), "sources": [asdict(i) for i in inventory]}
        content = json.dumps(payload, indent=2)
        dest = _write_export(f"evidence_package_{stamp}.json", content)
        return jsonify({"path": str(dest.relative_to(PROJECT_ROOT)), "content": content})

    if kind == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["screenshot_id", "sha256", "original_path", "processing_status", "title", "tags", "content_type"])
        for item in inventory:
            writer.writerow([item.screenshot_id, item.sha256, item.original_path, item.processing_status,
                              item.title or "", ";".join(item.tags), item.classification_confidence])
        content = buf.getvalue()
        dest = _write_export(f"index_{stamp}.csv", content)
        return jsonify({"path": str(dest.relative_to(PROJECT_ROOT)), "content": content})

    if kind == "text_ocr_bundle":
        parts = []
        for item in inventory:
            parts.append(f"=== SOURCE {item.screenshot_id} ({item.sha256}) ===")
            parts.append(item.corrected_ocr_excerpt or item.ocr_excerpt or "(no OCR text)")
            parts.append("")
        content = "\n".join(parts)
        dest = _write_export(f"ocr_bundle_{stamp}.txt", content)
        return jsonify({"path": str(dest.relative_to(PROJECT_ROOT)), "content": content})

    if kind in prompt_mode_by_kind:
        mode = prompt_mode_by_kind[kind]
        content = render_prompt(mode, "Export packet", inventory, "")
        dest = _write_export(f"{kind}_packet_{stamp}.md", content)
        return jsonify({"path": str(dest.relative_to(PROJECT_ROOT)), "content": content})

    return jsonify({"error": f"unknown export kind '{kind}'"}), 400


init_app_state()

if __name__ == "__main__":
    settings = get_settings()
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
