"""Flask route-level tests: error handling, scan concurrency guard, and
settings validation. Each test rebinds app._state to an isolated tmp_path
database/settings pair so tests never touch the real runtime/ directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import app as app_module
from config import Settings
from database import Database
from watcher import BoundedPoller


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "runtime" / "previews").mkdir(parents=True)
    (tmp_path / "runtime" / "exports").mkdir(parents=True)
    settings = Settings()
    settings.database_path = str(tmp_path / "runtime" / "database" / "test.db")
    db = Database(settings, tmp_path)
    db.connect()

    # Redirect every path config.py would otherwise read/write on the real
    # repo (settings.json, source_paths.json) into tmp_path, so route
    # handlers that call settings.save() / cfg.save_source_paths() during
    # these tests can never touch real project files.
    monkeypatch.setattr("config.SETTINGS_PATH", tmp_path / "config" / "settings.json")
    monkeypatch.setattr("config.SOURCE_PATHS_PATH", tmp_path / "config" / "source_paths.json")

    previous_state = dict(app_module._state)
    orig_project_root = app_module.PROJECT_ROOT

    app_module._state["settings"] = settings
    app_module._state["db"] = db
    app_module._state["last_scan"] = None
    app_module._state["poller"] = BoundedPoller(db, settings, lambda: [], tmp_path)
    app_module.PROJECT_ROOT = tmp_path

    app_module.app.testing = True
    with app_module.app.test_client() as c:
        yield c

    app_module.PROJECT_ROOT = orig_project_root
    db.close()
    app_module._state.clear()
    app_module._state.update(previous_state)


def test_malformed_json_returns_json_error_not_html(client):
    resp = client.post("/api/collections", data="{bad json", content_type="application/json")
    assert resp.status_code == 400
    assert resp.is_json
    assert "error" in resp.get_json()


def test_invalid_int_query_param_returns_400_json(client):
    resp = client.get("/api/library?limit=notanumber")
    assert resp.status_code == 400
    assert resp.is_json


def test_invalid_min_confidence_returns_400_json(client):
    resp = client.get("/api/search?min_confidence=abc")
    assert resp.status_code == 400
    assert resp.is_json


def test_unknown_route_returns_json_404(client):
    resp = client.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert resp.is_json


def test_scan_returns_409_when_already_in_progress(client):
    assert app_module._scan_lock.acquire(blocking=False)
    try:
        resp = client.post("/api/scan", json={})
        assert resp.status_code == 409
        assert "already in progress" in resp.get_json()["error"]
    finally:
        app_module._scan_lock.release()


def test_settings_put_rejects_invalid_types_without_saving(client):
    before = client.get("/api/settings").get_json()
    resp = client.put("/api/settings", json={"port": "not-a-port"})
    assert resp.status_code == 400
    body = resp.get_json()
    assert "port" in body["rejected"]
    after = client.get("/api/settings").get_json()
    assert after["port"] == before["port"]


def test_settings_put_coerces_string_numbers(client):
    resp = client.put("/api/settings", json={"max_normal_batch": "10"})
    assert resp.status_code == 200
    assert resp.get_json()["max_normal_batch"] == 10


def test_dashboard_empty_db_returns_zeros(client):
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["total_screenshots"] == 0
