"""Local OAuth and resumable YouTube upload support.

Credentials and refresh tokens stay on the user's device. Uploads are always
explicitly requested by the local Studio UI and are never triggered by render.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHUNK_BYTES = 8 * 1024 * 1024


class YouTubeError(RuntimeError):
    pass


def _atomic_secret(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def save_desktop_credentials(path: Path, data: dict) -> dict:
    installed = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(installed, dict) or not installed.get("client_id") or not installed.get("auth_uri") or not installed.get("token_uri"):
        raise YouTubeError("Upload a Google OAuth Desktop app client JSON with an installed section")
    parsed = urllib.parse.urlparse(str(installed["auth_uri"]))
    if parsed.scheme != "https" or parsed.hostname not in {"accounts.google.com", "oauth2.googleapis.com"}:
        raise YouTubeError("OAuth authorization endpoint is not a Google HTTPS endpoint")
    token_endpoint = urllib.parse.urlparse(str(installed["token_uri"]))
    if token_endpoint.scheme != "https" or token_endpoint.hostname != "oauth2.googleapis.com":
        raise YouTubeError("OAuth token endpoint must be Google's HTTPS endpoint")
    result = {key: str(installed.get(key, "")) for key in ("client_id", "client_secret", "token_uri")}
    result["auth_uri"] = AUTH_URL
    if not result["client_id"].endswith(".apps.googleusercontent.com"):
        raise YouTubeError("OAuth client ID does not look like a Google client ID")
    _atomic_secret(path, result)
    return {"status": "SAVED", "client_id_suffix": result["client_id"][-24:]}


def _post_form(url: str, values: dict[str, str]) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(values).encode(), headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        detail = getattr(exc, "read", lambda: b"")()
        raise YouTubeError(f"Google OAuth request failed: {detail.decode(errors='replace')[:400] or exc}") from None


class OAuthFlow:
    """One-shot loopback OAuth flow for a Google Desktop client on Termux."""
    def __init__(self, credential_path: Path, token_path: Path):
        self.credential_path = credential_path
        self.token_path = token_path
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._state = ""
        self._verifier = ""
        self._redirect = ""
        self._result = "NOT_CONNECTED"

    def start(self) -> str:
        if not self.credential_path.is_file():
            raise YouTubeError("Add the Google OAuth Desktop client JSON first")
        credentials = json.loads(self.credential_path.read_text(encoding="utf-8"))
        self._state = secrets.token_urlsafe(32)
        self._verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self._verifier.encode()).digest()).rstrip(b"=").decode()
        flow = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if query.get("state", [""])[0] != flow._state:
                    self.send_error(400, "OAuth state mismatch")
                    return
                error = query.get("error", [""])[0]
                code = query.get("code", [""])[0]
                if error or not code:
                    flow._result = "CANCELLED: " + (error or "authorization code missing")
                    body = b"ForgeWorld YouTube connection was not completed. You can return to Termux."
                    self.send_response(400)
                else:
                    try:
                        token = _post_form(credentials["token_uri"], {
                            "client_id": credentials["client_id"],
                            "client_secret": credentials.get("client_secret", ""),
                            "code": code,
                            "code_verifier": flow._verifier,
                            "grant_type": "authorization_code",
                            "redirect_uri": flow._redirect,
                        })
                        token["obtained_at"] = int(time.time())
                        token["youtube_channels"] = _list_mine_channels(token["access_token"])
                        _atomic_secret(flow.token_path, token)
                        flow._result = "CONNECTED"
                        body = b"YouTube connected to ForgeWorld Studio. You may close this tab and return to the app."
                        self.send_response(200)
                    except Exception as exc:
                        flow._result = "ERROR: " + str(exc)
                        body = ("Authorization failed: " + str(exc)).encode()
                        self.send_response(400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                threading.Thread(target=flow._shutdown, daemon=True).start()

            def log_message(self, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), CallbackHandler)
        self._server.daemon_threads = True
        port = self._server.server_address[1]
        self._redirect = f"http://127.0.0.1:{port}/oauth2callback"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        query = urllib.parse.urlencode({
            "client_id": credentials["client_id"], "redirect_uri": self._redirect,
            "response_type": "code", "scope": SCOPE, "access_type": "offline",
            "prompt": "consent", "state": self._state,
            "code_challenge": challenge, "code_challenge_method": "S256",
        })
        self._result = "AWAITING_USER"
        return AUTH_URL + "?" + query

    def _shutdown(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def status(self) -> dict:
        try:
            token = json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            token = {}
        return {"status": self._result if self._result != "NOT_CONNECTED" else ("CONNECTED" if token.get("refresh_token") else "NOT_CONNECTED"),
                "credentials_configured": self.credential_path.is_file(),
                "token_present": bool(token.get("refresh_token")),
                "channels": token.get("youtube_channels", [])}

    def access_token(self) -> str:
        try:
            token = json.loads(self.token_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise YouTubeError("Connect a YouTube account before uploading") from None
        expires_at = int(token.get("obtained_at", 0)) + int(token.get("expires_in", 0))
        if token.get("access_token") and expires_at > time.time() + 60:
            return token["access_token"]
        refresh = token.get("refresh_token")
        if not refresh:
            raise YouTubeError("Reconnect the YouTube account; no refresh token is stored")
        credentials = json.loads(self.credential_path.read_text(encoding="utf-8"))
        renewed = _post_form(credentials["token_uri"], {
            "client_id": credentials["client_id"], "client_secret": credentials.get("client_secret", ""),
            "refresh_token": refresh, "grant_type": "refresh_token",
        })
        renewed["refresh_token"] = refresh
        renewed["obtained_at"] = int(time.time())
        renewed["youtube_channels"] = token.get("youtube_channels", [])
        _atomic_secret(self.token_path, renewed)
        return renewed["access_token"]


def _google_request(url: str, method: str, token: str, body: bytes = b"", headers: dict | None = None):
    request_headers = {"Authorization": f"Bearer {token}", **(headers or {})}
    request = urllib.request.Request(url, data=body if method != "GET" else None, headers=request_headers, method=method)
    try:
        return urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        if exc.code == 308:
            return exc
        message = exc.read().decode(errors="replace")[:700]
        raise YouTubeError(f"YouTube API returned HTTP {exc.code}: {message}") from None
    except urllib.error.URLError as exc:
        raise YouTubeError(f"YouTube connection failed: {exc.reason}") from None


def _list_mine_channels(token: str) -> list[dict]:
    url = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true&maxResults=50"
    with _google_request(url, "GET", token) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [{"channel_id": item.get("id", ""), "title": item.get("snippet", {}).get("title", ""),
             "custom_url": item.get("snippet", {}).get("customUrl", "")}
            for item in data.get("items", [])]


def upload_video(token_provider: Callable[[], str], video_path: Path, metadata: dict,
                 confirm: bool, progress: Callable[[dict], None] | None = None) -> dict:
    """Explicit, resumable upload of a rendered MP4 to the authorized channel."""
    if confirm is not True:
        raise YouTubeError("Upload requires explicit user confirmation")
    path = Path(video_path).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != ".mp4":
        raise YouTubeError("Choose a rendered MP4 file")
    title = str(metadata.get("title", "")).strip()
    description = str(metadata.get("description", ""))
    privacy = metadata.get("privacy_status")
    if not title or len(title) > 100 or len(description) > 5000:
        raise YouTubeError("YouTube title is required (maximum 100 characters); description limit is 5000")
    if privacy not in {"private", "unlisted", "public"}:
        raise YouTubeError("Choose private, unlisted, or public visibility")
    tags = metadata.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 30 or any(not isinstance(tag, str) or len(tag) > 100 for tag in tags):
        raise YouTubeError("Tags must be a list of up to 30 short text values")
    if metadata.get("audience") not in {"made_for_kids", "not_made_for_kids"}:
        raise YouTubeError("Choose the audience designation before upload")
    if metadata.get("altered_content") not in {True, False}:
        raise YouTubeError("Choose the altered or synthetic content disclosure before upload")
    resource = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": str(metadata.get("category_id", "22"))},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": metadata["audience"] == "made_for_kids",
                   "containsSyntheticMedia": metadata["altered_content"]},
    }
    token = token_provider()
    size = path.stat().st_size
    mime = "video/mp4"
    init = urllib.request.Request(
        UPLOAD_URL + "?uploadType=resumable&part=snippet,status",
        data=json.dumps(resource).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": mime},
    )
    try:
        with urllib.request.urlopen(init, timeout=60) as response:
            session = response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        raise YouTubeError(f"Could not start YouTube upload (HTTP {exc.code}): {exc.read().decode(errors='replace')[:700]}") from None
    except urllib.error.URLError as exc:
        raise YouTubeError(f"Could not start YouTube upload: {exc.reason}") from None
    parsed = urllib.parse.urlparse(session)
    if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
        raise YouTubeError("Google returned an unexpected resumable upload URL")

    offset = 0
    with path.open("rb") as stream:
        while offset < size:
            stream.seek(offset)
            chunk = stream.read(min(CHUNK_BYTES, size - offset))
            end = offset + len(chunk) - 1
            headers = {"Content-Type": mime, "Content-Length": str(len(chunk)), "Content-Range": f"bytes {offset}-{end}/{size}"}
            try:
                response = _google_request(session, "PUT", token, chunk, headers)
                if response.status in {200, 201}:
                    result = json.loads(response.read().decode())
                    if progress:
                        progress({"uploaded_bytes": size, "total_bytes": size})
                    return {"status": "UPLOADED", "video_id": result.get("id"),
                            "watch_url": f"https://www.youtube.com/watch?v={result.get('id')}",
                            "privacy_status": privacy}
                if response.status == 308:
                    received = response.headers.get("Range", "")
                    offset = int(received.rsplit("-", 1)[-1]) + 1 if received else 0
                else:
                    raise YouTubeError(f"Unexpected YouTube upload response: HTTP {response.status}")
            except YouTubeError:
                raise
            except Exception as exc:
                time.sleep(1)
                status = _google_request(session, "PUT", token, b"", {
                    "Content-Length": "0", "Content-Range": f"bytes */{size}"})
                if status.status == 308:
                    received = status.headers.get("Range", "")
                    offset = int(received.rsplit("-", 1)[-1]) + 1 if received else 0
                else:
                    raise YouTubeError(f"Upload interrupted and could not resume: {exc}") from None
            if progress:
                progress({"uploaded_bytes": offset, "total_bytes": size})
    raise YouTubeError("YouTube upload ended without a completed video response")
