from __future__ import annotations

import json
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from video_creation.studio import Studio, make_handler
from video_creation.youtube import YouTubeError, save_desktop_credentials, upload_video


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="fw-studio-test-"))
        self.studio = Studio(self.temp)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.studio))
        self.studio.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.studio.port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.temp, ignore_errors=True)

    def request(self, path, method="GET", data=None, content_type="application/json"):
        body = data if isinstance(data, bytes) else (json.dumps(data).encode() if data is not None else None)
        headers = {}
        if body is not None:
            headers.update({"Content-Type": content_type, "X-ForgeWorld-Token": self.studio.csrf,
                            "Origin": self.base})
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_serves_studio_shell_and_requires_token_for_mutations(self):
        status, page = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b"ForgeWorld Video Studio", page)
        req = urllib.request.Request(self.base + "/api/youtube/connect", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json", "Origin": self.base})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_asset_upload_and_project_creation(self):
        status, body = self.request("/api/assets?filename=owned-photo.jpg", "POST", b"local-fixture",
                                    "application/octet-stream")
        self.assertEqual(status, 201)
        asset_id = json.loads(body)["asset"]["asset_id"]
        status, body = self.request("/api/projects", "POST", {"project_id": "phone-test", "asset_ids": [asset_id],
                                   "format": "vertical", "duration_seconds": 3, "title": "Opening title",
                                   "caption": "A local caption", "description": "Test description"})
        self.assertEqual(status, 201, body.decode())
        project = json.loads((self.temp / "projects" / "phone-test" / "project.json").read_text())
        self.assertEqual(project["scenes"][0]["overlay_text"], "Opening title")
        self.assertEqual(project["scenes"][0]["captions"][0]["text"], "A local caption")
        status, body = self.request("/api/projects/phone-test")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["youtube_metadata"]["privacy_status"], "private")

    def test_video_file_serves_byte_ranges(self):
        output = self.studio.exports / "range-preview-preview.mp4"
        output.write_bytes(b"0123456789")
        status, body = self.request("/api/download/range-preview/preview")
        self.assertEqual(status, 200)
        req = urllib.request.Request(self.base + "/api/download/range-preview/preview", headers={"Range": "bytes=3-6"})
        with urllib.request.urlopen(req) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"3456")


class YouTubeLocalTests(unittest.TestCase):
    def test_saves_only_google_desktop_oauth_configuration(self):
        root = Path(tempfile.mkdtemp(prefix="fw-oauth-test-"))
        try:
            path = root / "private" / "client.json"
            result = save_desktop_credentials(path, {"installed": {"client_id": "abc.apps.googleusercontent.com",
                                                 "client_secret": "local-secret", "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                                 "token_uri": "https://oauth2.googleapis.com/token"}})
            self.assertEqual(result["status"], "SAVED")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(YouTubeError):
                save_desktop_credentials(path, {"installed": {"client_id": "abc.apps.googleusercontent.com",
                                                   "auth_uri": "https://evil.invalid/", "token_uri": "https://oauth2.googleapis.com/token"}})
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_upload_requires_explicit_confirmation_before_network(self):
        with self.assertRaisesRegex(YouTubeError, "explicit user confirmation"):
            upload_video(lambda: "unused", Path("missing.mp4"), {}, False)


if __name__ == "__main__":
    unittest.main()
