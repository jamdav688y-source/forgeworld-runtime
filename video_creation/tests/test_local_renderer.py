from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from video_creation.assets import create_quickstart_project
from video_creation.ffmpeg_backend import RenderError, probe, render_project
from video_creation.project import ProjectError, PROJECT_SCHEMA, resolve_assets, validate_project


def make_project(root: Path) -> dict:
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    rows = []
    for asset_id, color in (("red", "red"), ("blue", "blue")):
        path = assets / f"{asset_id}.png"
        subprocess.run([shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                        "-i", f"color=c={color}:s=320x240", "-frames:v", "1", str(path)],
                       check=True, capture_output=True)
        rows.append({"asset_id": asset_id, "path": path.name,
                     "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                     "kind": "image", "rights_status": "GENERATED_LOCAL"})
    return {
        "schema_version": PROJECT_SCHEMA,
        "project_id": "renderer-fixture",
        "revision": 1,
        "asset_root": "assets",
        "profile": {"width": 360, "height": 640, "fps_num": 30, "fps_den": 1,
                    "fit": "contain", "crf": 25},
        "assets": rows,
        "scenes": [
            {"scene_id": "scene-a", "production_scene_id": None, "asset_id": "red",
             "duration_ms": 1000, "source_in_ms": 0, "fit": "contain", "label": "DRAMATIZATION",
             "source_refs": ["fixture:red"], "citations": [], "disclosures": ["Synthetic color card"], "overlay_text": "First scene: test",
             "captions": [{"start_ms": 100, "end_ms": 850, "text": "Local render caption"}]},
            {"scene_id": "scene-b", "production_scene_id": None, "asset_id": "blue",
             "duration_ms": 1000, "source_in_ms": 0, "fit": "cover", "label": "USER_AUTHORED",
             "source_refs": ["fixture:blue"], "citations": [], "disclosures": [], "overlay_text": "Second scene", "captions": []},
        ],
        "audio": None,
        "lineage": {"package_id": None, "candidate_id": None, "candidate_content_id": None,
                    "package_version": None, "publication_authorized": False},
    }


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "local FFmpeg tools are required")
class LocalRendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="fw-video-test-"))
        self.project = make_project(self.temp)

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_validates_project_and_pinned_assets(self):
        self.assertIs(validate_project(self.project), self.project)
        self.assertEqual(set(resolve_assets(self.project, self.temp)), {"red", "blue"})

    def test_rejects_path_traversal_and_unknown_fields(self):
        bad = json.loads(json.dumps(self.project))
        bad["assets"][0]["path"] = "../outside.png"
        with self.assertRaises(ProjectError):
            validate_project(bad)
        bad = json.loads(json.dumps(self.project))
        bad["unexpected"] = True
        with self.assertRaises(ProjectError):
            validate_project(bad)

    def test_rejects_changed_asset_hash(self):
        path = self.temp / "assets" / "red.png"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ProjectError, "hash changed"):
            resolve_assets(self.project, self.temp)

    def test_rejects_symlinked_asset_root_escape(self):
        outside = self.temp.parent / f"{self.temp.name}-outside"
        outside.mkdir()
        assets = self.temp / "linked-assets"
        try:
            assets.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlinks unavailable on this platform")
        project = json.loads(json.dumps(self.project))
        project["asset_root"] = "linked-assets"
        with self.assertRaisesRegex(ProjectError, "asset_root escapes"):
            resolve_assets(project, self.temp)
        shutil.rmtree(outside, ignore_errors=True)

    def test_quickstart_imports_selected_media_and_writes_project(self):
        quick = self.temp / "quickstart"
        project = create_quickstart_project(quick, "quick-video",
                                            [self.temp / "assets" / "red.png", self.temp / "assets" / "blue.png"],
                                            duration_ms=750, width=360, height=640)
        self.assertEqual(project["project_id"], "quick-video")
        self.assertEqual(len(project["scenes"]), 2)
        self.assertEqual(len(resolve_assets(project, quick)), 2)
        self.assertTrue((quick / "project.json").is_file())

    def test_renders_two_scene_vertical_video_and_receipt(self):
        output = self.temp / "out" / "sample.mp4"
        result = render_project(self.project, self.temp, output, mode="final")
        self.assertEqual(result["status"], "RENDERED")
        self.assertTrue(output.is_file())
        self.assertTrue(Path(result["receipt_path"]).is_file())
        self.assertTrue(Path(result["captions_path"]).is_file())
        media = probe(output)
        video = next(stream for stream in media["streams"] if stream["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"], video["pix_fmt"]), (360, 640, "yuv420p"))
        receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
        self.assertFalse(receipt["publication_authorized"])
        self.assertEqual(receipt["upload_status"], "NOT_ATTEMPTED")
        self.assertEqual(receipt["evidence_status"], "GENERATED_MEDIA_NOT_SOURCE_EVIDENCE")
        self.assertEqual(receipt["output"]["sha256"], result["output_sha256"])

    def test_handles_filter_text_and_output_paths_with_punctuation(self):
        project = json.loads(json.dumps(self.project))
        project["scenes"][0]["overlay_text"] = "Let's render: 50%, safely [today]"
        output_dir = self.temp / "folder's name"
        output = output_dir / "punctuation.mp4"
        result = render_project(project, self.temp, output)
        self.assertTrue(Path(result["output_path"]).is_file())

    def test_renders_deterministic_still_camera_moves(self):
        for motion in ("push_in", "pull_out", "pan_left", "pan_right"):
            project = json.loads(json.dumps(self.project))
            project["scenes"][0]["motion"] = motion
            output = self.temp / f"{motion}.mp4"
            result = render_project(project, self.temp, output, mode="preview")
            self.assertEqual(result["status"], "RENDERED", motion)
            self.assertTrue(output.is_file(), motion)

    def test_refuses_to_overwrite_without_explicit_flag(self):
        output = self.temp / "sample.mp4"
        render_project(self.project, self.temp, output)
        with self.assertRaises(RenderError) as caught:
            render_project(self.project, self.temp, output)
        self.assertEqual(caught.exception.code, "OUTPUT_EXISTS")

    def test_renders_trimmed_video_with_audio_mix(self):
        assets = self.temp / "assets"
        clip = assets / "clip.mp4"
        tone = assets / "tone.wav"
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "color=c=green:s=320x240:d=1", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac", "-t", "1", str(clip)],
                       check=True, capture_output=True)
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "sine=frequency=220:duration=3", "-c:a", "pcm_s16le", str(tone)],
                       check=True, capture_output=True)
        def row(asset_id, path, kind):
            return {"asset_id": asset_id, "path": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "kind": kind, "rights_status": "GENERATED_LOCAL"}
        project = json.loads(json.dumps(self.project))
        project["assets"] = [row("clip", clip, "video"), row("tone", tone, "audio")]
        project["scenes"] = [
            {"scene_id": "trimmed", "production_scene_id": None, "asset_id": "clip",
             "duration_ms": 700, "source_in_ms": 100, "fit": "contain", "label": "USER_AUTHORED",
             "source_refs": [], "citations": [], "disclosures": [], "overlay_text": "Trimmed clip",
             "captions": []}
        ]
        project["audio"] = {"asset_id": "tone", "gain": 0.2, "fade_out_ms": 100}
        output = self.temp / "with-audio.mp4"
        result = render_project(project, self.temp, output)
        media = probe(output)
        self.assertTrue(any(stream["codec_type"] == "audio" for stream in media["streams"]))
        self.assertEqual(result["status"], "RENDERED")


if __name__ == "__main__":
    unittest.main()
