"""Phone-first local web studio for Termux. Bind only to loopback."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import secrets
import threading
import tempfile
import time
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .assets import create_quickstart_project, infer_kind
from .ffmpeg_backend import RenderError, doctor, probe, render_project
from .instructions import compile_instructions
from .project import ProjectError, validate_project, write_project
from .youtube import OAuthFlow, YouTubeError, save_desktop_credentials, upload_video

MAX_UPLOAD = 250 * 1024 * 1024
PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


class Studio:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.inbox = self.root / "inbox"
        self.projects = self.root / "projects"
        self.exports = self.root / "exports"
        self.secrets = self.root / "private"
        for path in (self.inbox, self.projects, self.exports, self.secrets):
            path.mkdir(parents=True, exist_ok=True)
        os.chmod(self.secrets, 0o700)
        self.csrf = secrets.token_urlsafe(32)
        self.port = 8765
        self.oauth = OAuthFlow(self.secrets / "google-oauth-client.json", self.secrets / "youtube-token.json")
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.web_root = Path(__file__).with_name("web")

    def asset_records(self) -> list[dict]:
        records = []
        for info in self.inbox.glob("*.json"):
            try:
                row = json.loads(info.read_text(encoding="utf-8"))
                path = self.inbox / row["stored_name"]
                if path.is_file():
                    records.append({"asset_id": row["asset_id"], "name": row["name"], "kind": row["kind"],
                                   "bytes": path.stat().st_size, "added_at": row.get("added_at", path.stat().st_mtime)})
            except (OSError, KeyError, json.JSONDecodeError):
                continue
        return sorted(records, key=lambda row: row["added_at"], reverse=True)

    def project_path(self, project_id: str) -> Path:
        if not PROJECT_ID.fullmatch(project_id):
            raise ProjectError("project ID is invalid")
        path = (self.projects / project_id).resolve()
        path.relative_to(self.projects.resolve())
        return path

    def load_project(self, project_id: str) -> dict:
        path = self.project_path(project_id) / "project.json"
        project = json.loads(path.read_text(encoding="utf-8"))
        return validate_project(project)

    def start_job(self, kind: str, worker) -> str:
        with self.lock:
            running = [job for job in self.jobs.values() if job["status"] in {"QUEUED", "RUNNING"}]
            if len(running) >= 1:
                raise ProjectError("one render or upload is already running; wait for it to finish")
            job_id = uuid.uuid4().hex[:12]
            self.jobs[job_id] = {"job_id": job_id, "kind": kind, "status": "QUEUED", "created_at": time.time()}

        def run():
            with self.lock:
                self.jobs[job_id]["status"] = "RUNNING"
                self.jobs[job_id]["started_at"] = time.time()
            try:
                result = worker(lambda update: self._progress(job_id, update))
                with self.lock:
                    self.jobs[job_id].update({"status": "DONE", "result": result, "finished_at": time.time()})
            except Exception as exc:
                with self.lock:
                    self.jobs[job_id].update({"status": "ERROR", "error": str(exc), "finished_at": time.time()})
        threading.Thread(target=run, daemon=True).start()
        return job_id

    def _progress(self, job_id: str, update: dict) -> None:
        with self.lock:
            self.jobs[job_id].update(update)


def _json(handler: BaseHTTPRequestHandler, status: int, value: dict):
    body = json.dumps(value, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def make_handler(studio: Studio):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ForgeWorldStudio/0.1"

        def log_message(self, fmt, *args):
            # Local media filenames, metadata and OAuth callback parameters stay out of logs.
            if self.path.startswith("/api"):
                return
            super().log_message(fmt, *args)

        def _body(self, maximum=1024 * 1024) -> bytes:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > maximum:
                raise ProjectError(f"request body exceeds {maximum} bytes")
            body = self.rfile.read(length)
            if len(body) != length:
                raise ProjectError("request body ended early")
            return body

        def _json_body(self) -> dict:
            try:
                value = json.loads(self._body().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ProjectError("request must contain valid JSON") from None
            if not isinstance(value, dict):
                raise ProjectError("request JSON must be an object")
            return value

        def _stream_asset(self, destination: Path) -> int:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_UPLOAD:
                raise ProjectError(f"asset size must be 1 byte through {MAX_UPLOAD // (1024 * 1024)} MB")
            fd, temporary_name = tempfile.mkstemp(prefix=".incoming-", dir=studio.inbox)
            written = 0
            try:
                with os.fdopen(fd, "wb") as output:
                    while written < length:
                        block = self.rfile.read(min(1024 * 1024, length - written))
                        if not block:
                            raise ProjectError("asset upload ended before all bytes arrived")
                        output.write(block)
                        written += len(block)
                os.replace(temporary_name, destination)
                return written
            finally:
                Path(temporary_name).unlink(missing_ok=True)

        def _authorized(self) -> bool:
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            expected = f"http://{host}"
            return (self.headers.get("X-ForgeWorld-Token", "") == studio.csrf
                    and (not origin or origin == expected)
                    and host in {f"127.0.0.1:{studio.port}", f"localhost:{studio.port}"})

        def _serve_file(self, path: Path, content_type: str, attachment: str | None = None):
            try:
                size = path.stat().st_size
                start, end = 0, size - 1
                status = 200
                requested = self.headers.get("Range", "")
                if requested.startswith("bytes="):
                    left, _, right = requested[6:].partition("-")
                    if not left and right:
                        count = int(right)
                        start = max(0, size - count)
                    else:
                        start = int(left)
                        if right:
                            end = min(end, int(right))
                    if start > end or start >= size:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.end_headers()
                        return
                    status = 206
            except (OSError, ValueError):
                _json(self, 404, {"error": "not found"})
                return
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            if attachment:
                safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", attachment)
                self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with path.open("rb") as media:
                media.seek(start)
                remaining = end - start + 1
                while remaining:
                    block = media.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            if route == "/":
                body = studio.web_root.joinpath("index.html").read_text(encoding="utf-8").replace("__FW_TOKEN__", studio.csrf).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            elif route == "/manifest.webmanifest":
                self._serve_file(studio.web_root / "manifest.webmanifest", "application/manifest+json")
            elif route == "/sw.js":
                self._serve_file(studio.web_root / "sw.js", "text/javascript; charset=utf-8")
            elif route == "/icon.svg":
                self._serve_file(studio.web_root / "icon.svg", "image/svg+xml")
            elif route == "/api/health":
                try:
                    diagnostics = doctor()
                    _json(self, 200, {"status": "READY" if not diagnostics["missing_features"] else "LIMITED",
                                      "version": diagnostics["version"], "missing_features": diagnostics["missing_features"],
                                      "gpl_enabled": diagnostics["gpl_enabled"]})
                except Exception as exc:
                    _json(self, 200, {"status": "LIMITED", "error": str(exc)})
            elif route == "/api/assets":
                _json(self, 200, {"assets": studio.asset_records()})
            elif route == "/api/projects":
                projects = []
                for path in sorted(studio.projects.iterdir()):
                    project_file = path / "project.json"
                    if path.is_dir() and project_file.is_file():
                        try:
                            p = json.loads(project_file.read_text(encoding="utf-8"))
                            projects.append({"project_id": p["project_id"], "revision": p["revision"],
                                             "scenes": len(p["scenes"]), "duration_ms": sum(s["duration_ms"] for s in p["scenes"])})
                        except (OSError, KeyError, json.JSONDecodeError):
                            pass
                _json(self, 200, {"projects": projects})
            elif route.startswith("/api/projects/"):
                project_id = route.split("/")[3]
                project_dir = studio.project_path(project_id)
                project = studio.load_project(project_id)
                try:
                    metadata = json.loads((project_dir / "youtube-metadata.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    metadata = {}
                _json(self, 200, {"project": project, "youtube_metadata": metadata,
                                  "duration_seconds": round(sum(s["duration_ms"] for s in project["scenes"]) / 1000, 3)})
            elif route.startswith("/api/jobs/"):
                job_id = route.rsplit("/", 1)[-1]
                with studio.lock:
                    job = studio.jobs.get(job_id)
                _json(self, 200 if job else 404, job or {"error": "job not found"})
            elif route == "/api/youtube/status":
                _json(self, 200, studio.oauth.status())
            elif route.startswith("/api/download/"):
                parts = route.strip("/").split("/")
                if len(parts) != 4 or parts[3] not in {"preview", "final"}:
                    _json(self, 404, {"error": "not found"})
                    return
                project_id, mode = parts[2], parts[3]
                if not PROJECT_ID.fullmatch(project_id):
                    _json(self, 404, {"error": "not found"})
                    return
                path = studio.exports / f"{project_id}-{mode}.mp4"
                try:
                    path.resolve().relative_to(studio.exports.resolve())
                except ValueError:
                    _json(self, 404, {"error": "not found"})
                    return
                self._serve_file(path, "video/mp4", path.name)
            else:
                _json(self, 404, {"error": "not found"})

        def do_POST(self):
            if not self._authorized():
                _json(self, 403, {"error": "local session token or origin check failed; reload the Studio page"})
                return
            parsed = urllib.parse.urlparse(self.path)
            route = parsed.path
            try:
                if route == "/api/assets":
                    query = urllib.parse.parse_qs(parsed.query)
                    original = Path(query.get("filename", ["media"])[0]).name[:180]
                    extension = Path(original).suffix.lower()
                    temp_path = studio.inbox / ("probe" + extension)
                    try:
                        infer_kind(temp_path)
                    except ProjectError:
                        raise ProjectError("supported assets: common images, video, or audio files") from None
                    asset_id = uuid.uuid4().hex[:16]
                    stored_name = asset_id + extension
                    destination = studio.inbox / stored_name
                    length = self._stream_asset(destination)
                    try:
                        kind = infer_kind(destination)
                    except Exception:
                        destination.unlink(missing_ok=True)
                        raise
                    info = {"asset_id": asset_id, "stored_name": stored_name, "name": original, "kind": kind, "added_at": time.time()}
                    (studio.inbox / f"{asset_id}.json").write_text(json.dumps(info), encoding="utf-8")
                    _json(self, 201, {"asset": {"asset_id": asset_id, "name": original, "kind": kind, "bytes": length}})
                elif route == "/api/instructions":
                    data = self._json_body()
                    plan = compile_instructions(data.get("instructions", ""), studio.asset_records())
                    if not plan["visual_assets"]:
                        raise ProjectError("Add the source artwork or clips once in Source media. After that, instructions can drive the project and render.")
                    visual_paths = []
                    for record in plan["visual_assets"]:
                        info = json.loads((studio.inbox / f"{record['asset_id']}.json").read_text(encoding="utf-8"))
                        visual_paths.append(studio.inbox / info["stored_name"])
                    selected = list(visual_paths)
                    if plan["audio_asset"]:
                        info = json.loads((studio.inbox / f"{plan['audio_asset']['asset_id']}.json").read_text(encoding="utf-8"))
                        selected.append(studio.inbox / info["stored_name"])
                    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
                    project_id = f"{plan['project_id_base'][:32]}-{stamp}"
                    project_dir = studio.project_path(project_id)
                    width, height = (720, 1280) if plan["format"] == "vertical" else ((1280, 720) if plan["format"] == "landscape" else (720, 720))
                    project = create_quickstart_project(project_dir, project_id, selected,
                                                        plan["duration_seconds"] * 1000, width, height, "contain")
                    for scene in project["scenes"]:
                        asset = next(a for a in project["assets"] if a["asset_id"] == scene["asset_id"])
                        if asset["kind"] == "image":
                            scene["motion"] = plan["motion"]
                    project["scenes"][0]["overlay_text"] = plan["title"]
                    if plan["caption"]:
                        project["scenes"][0]["captions"] = [{"start_ms": 0,
                            "end_ms": min(project["scenes"][0]["duration_ms"], 5000), "text": plan["caption"]}]
                    project["revision"] = 2
                    write_project(project_dir / "project.json", project, overwrite=True)
                    (project_dir / "creative-brief.txt").write_text(plan["brief"] + "\n", encoding="utf-8")
                    (project_dir / "instruction-plan.json").write_text(json.dumps({k: v for k, v in plan.items()
                        if k not in {"visual_assets", "audio_asset"}}, indent=2), encoding="utf-8")
                    metadata = {"title": plan["title"], "description": plan["description"], "tags": plan["tags"],
                                "privacy_status": "private", "audience": "not_made_for_kids",
                                "altered_content": False, "category_id": "22"}
                    (project_dir / "youtube-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                    job_id = studio.start_job("preview_render", lambda progress: render_project(project, project_dir,
                        studio.exports / f"{project_id}-preview.mp4", "preview", overwrite=True))
                    _json(self, 202, {"status": "CREATED", "project_id": project_id, "job_id": job_id,
                                      "title": plan["title"], "assumptions": plan["assumptions"],
                                      "limitations": plan["limitations"]})
                elif route == "/api/projects":
                    data = self._json_body()
                    asset_ids = data.get("asset_ids")
                    if not isinstance(asset_ids, list) or not 1 <= len(asset_ids) <= 64:
                        raise ProjectError("select 1 to 64 image or video assets")
                    if len(set(asset_ids)) != len(asset_ids):
                        raise ProjectError("duplicate asset selection")
                    records = {row["asset_id"]: row for row in studio.asset_records()}
                    selected = []
                    for asset_id in asset_ids:
                        row = records.get(asset_id)
                        if not row or row["kind"] not in {"image", "video"}:
                            raise ProjectError("each selected scene asset must be an uploaded image or video")
                        info = json.loads((studio.inbox / f"{asset_id}.json").read_text(encoding="utf-8"))
                        selected.append(studio.inbox / info["stored_name"])
                    project_id = str(data.get("project_id", "")).lower()
                    if not PROJECT_ID.fullmatch(project_id):
                        raise ProjectError("project ID must use lowercase letters, numbers, or hyphens")
                    project_dir = studio.project_path(project_id)
                    if (project_dir / "project.json").exists():
                        raise ProjectError("that project ID already exists")
                    width, height = (720, 1280) if data.get("format") == "vertical" else ((1280, 720) if data.get("format") == "landscape" else (720, 720))
                    duration_ms = int(data.get("duration_seconds", 3)) * 1000
                    audio_id = data.get("audio_asset_id")
                    if audio_id:
                        row = records.get(audio_id)
                        if not row or row["kind"] != "audio":
                            raise ProjectError("selected music must be an uploaded audio asset")
                        info = json.loads((studio.inbox / f"{audio_id}.json").read_text(encoding="utf-8"))
                        selected.append(studio.inbox / info["stored_name"])
                    project = create_quickstart_project(project_dir, project_id, selected, duration_ms, width, height, "contain")
                    motion = data.get("still_motion", "push_in")
                    if motion not in {"static", "push_in", "pull_out", "pan_left", "pan_right"}:
                        raise ProjectError("unsupported still-image motion preset")
                    for scene in project["scenes"]:
                        asset = next(a for a in project["assets"] if a["asset_id"] == scene["asset_id"])
                        if asset["kind"] == "image":
                            scene["motion"] = motion
                    title = str(data.get("title", "")).strip()[:180]
                    caption = str(data.get("caption", "")).strip()[:500]
                    if title:
                        project["scenes"][0]["overlay_text"] = title
                    if caption:
                        project["scenes"][0]["captions"] = [{"start_ms": 0, "end_ms": min(duration_ms, 5000), "text": caption}]
                    project["revision"] = 2
                    write_project(project_dir / "project.json", project, overwrite=True)
                    metadata = {"title": title or project_id, "description": str(data.get("description", ""))[:5000],
                                "tags": [], "privacy_status": "private", "audience": "not_made_for_kids",
                                "altered_content": False, "category_id": "22"}
                    (project_dir / "youtube-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                    _json(self, 201, {"status": "CREATED", "project_id": project_id, "revision": 2,
                                      "project_file": str(project_dir / "project.json"), "scenes": len(project["scenes"])})
                elif route.startswith("/api/projects/") and route.endswith("/render"):
                    project_id = route.split("/")[3]
                    data = self._json_body()
                    mode = data.get("mode", "preview")
                    if mode not in {"preview", "final"}:
                        raise ProjectError("render mode must be preview or final")
                    project = studio.load_project(project_id)
                    output = studio.exports / f"{project_id}-{mode}.mp4"
                    job_id = studio.start_job("render", lambda progress: render_project(project, studio.project_path(project_id), output, mode, overwrite=True))
                    _json(self, 202, {"status": "QUEUED", "job_id": job_id})
                elif route == "/api/youtube/credentials":
                    data = self._json_body()
                    result = save_desktop_credentials(studio.secrets / "google-oauth-client.json", data)
                    _json(self, 200, result)
                elif route == "/api/youtube/connect":
                    url = studio.oauth.start()
                    _json(self, 200, {"status": "AWAITING_USER", "authorization_url": url})
                elif route.startswith("/api/projects/") and route.endswith("/metadata"):
                    project_id = route.split("/")[3]
                    studio.load_project(project_id)
                    data = self._json_body()
                    metadata = {key: data.get(key) for key in ("title", "description", "tags", "privacy_status", "audience", "altered_content", "category_id")}
                    if not isinstance(metadata["title"], str) or not metadata["title"].strip() or len(metadata["title"]) > 100:
                        raise ProjectError("YouTube title is required and must be at most 100 characters")
                    if not isinstance(metadata["description"], str) or len(metadata["description"]) > 5000:
                        raise ProjectError("YouTube description must be at most 5000 characters")
                    if not isinstance(metadata["tags"], list) or len(metadata["tags"]) > 30 or any(not isinstance(tag, str) or len(tag) > 100 for tag in metadata["tags"]):
                        raise ProjectError("YouTube tags must be up to 30 values, each at most 100 characters")
                    if metadata["privacy_status"] not in {"private", "unlisted", "public"}:
                        raise ProjectError("invalid YouTube visibility")
                    if metadata["audience"] not in {"made_for_kids", "not_made_for_kids"} or metadata["altered_content"] not in {True, False}:
                        raise ProjectError("audience and synthetic-content disclosures must be selected")
                    (studio.project_path(project_id) / "youtube-metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                    _json(self, 200, {"status": "SAVED"})
                elif route == "/api/youtube/upload":
                    data = self._json_body()
                    project_id = data.get("project_id", "")
                    if data.get("confirm_upload") is not True or data.get("confirmed_privacy_status") != data.get("privacy_status"):
                        raise YouTubeError("Upload needs an explicit confirmation of the displayed visibility setting")
                    channels = studio.oauth.status().get("channels", [])
                    target = channels[0] if channels else None
                    if not target or data.get("confirmed_channel_id") != target.get("channel_id"):
                        raise YouTubeError("Reconnect YouTube and confirm the connected channel before uploading")
                    project = studio.load_project(project_id)
                    video = studio.exports / f"{project_id}-final.mp4"
                    if not video.is_file():
                        raise YouTubeError("Render a final MP4 before starting upload")
                    metadata = {key: data.get(key) for key in ("title", "description", "tags", "privacy_status", "audience", "altered_content", "category_id")}
                    audit = {"project_id": project_id, "file": video.name, "title": str(metadata["title"] or "")[:100],
                             "channel_id": target.get("channel_id"), "channel_title": target.get("title"),
                             "privacy_status": metadata["privacy_status"], "user_confirmed": True, "status": "STARTED", "created_at": time.time()}
                    audit_path = project_path = studio.project_path(project_id) / "upload-attempt.json"
                    audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")

                    def do_upload(progress):
                        try:
                            result = upload_video(studio.oauth.access_token, video, metadata, True, progress)
                            audit.update({"status": "UPLOADED", "video_id": result.get("video_id"), "watch_url": result.get("watch_url"), "completed_at": time.time()})
                            return result
                        except Exception as exc:
                            audit.update({"status": "ERROR", "error": str(exc), "completed_at": time.time()})
                            raise
                        finally:
                            audit_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")
                    job_id = studio.start_job("youtube_upload", do_upload)
                    _json(self, 202, {"status": "QUEUED", "job_id": job_id, "privacy_status": metadata["privacy_status"]})
                else:
                    _json(self, 404, {"error": "not found"})
            except (ProjectError, RenderError, YouTubeError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                _json(self, 400, {"status": "ERROR", "error": str(exc)})
            except Exception as exc:
                _json(self, 500, {"status": "ERROR", "error": f"internal error: {type(exc).__name__}"})

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ForgeWorld Video Studio on this device")
    parser.add_argument("--workspace", type=Path, default=Path.home() / ".forgeworld-video")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="print the URL without asking Android to open a browser")
    args = parser.parse_args(argv)
    studio = Studio(args.workspace)
    studio.port = args.port
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(studio))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print(f"ForgeWorld Video Studio is running at {url}")
    print(f"Local workspace: {studio.root}")
    print("Keep this Termux session running. Press Ctrl+C to stop the Studio.")
    if not args.no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("Stopping ForgeWorld Video Studio")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
