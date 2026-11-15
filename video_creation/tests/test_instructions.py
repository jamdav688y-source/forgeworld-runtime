from __future__ import annotations

import unittest

from video_creation.instructions import compile_instructions


class InstructionCompilerTests(unittest.TestCase):
    def setUp(self):
        self.assets = [
            {"asset_id": "new-photo", "name": "VernalArtwork.png", "kind": "image", "added_at": 20},
            {"asset_id": "old-clip", "name": "opening.mp4", "kind": "video", "added_at": 10},
            {"asset_id": "music", "name": "score.wav", "kind": "audio", "added_at": 30},
        ]

    def test_compiles_vernal_brief_to_local_scene_recipe(self):
        result = compile_instructions(
            "Create exactly 10 seconds of vertical video from my newest artwork.\n"
            "Title: The Vernal Difference\nCamera: slow push-in\n"
            "Caption: A new world begins to move.\nAdd music.", self.assets)
        self.assertEqual(result["title"], "The Vernal Difference")
        self.assertEqual(result["duration_seconds"], 10)
        self.assertEqual(result["format"], "vertical")
        self.assertEqual(result["motion"], "push_in")
        self.assertEqual(result["caption"], "A new world begins to move.")
        self.assertEqual(result["visual_assets"][0]["asset_id"], "new-photo")
        self.assertEqual(result["audio_asset"]["asset_id"], "music")

    def test_selects_all_visuals_only_when_instruction_requests_all(self):
        result = compile_instructions("Make a 16:9 montage using all my clips, pan left.", self.assets)
        self.assertEqual(result["format"], "landscape")
        self.assertEqual([a["asset_id"] for a in result["visual_assets"]], ["new-photo", "old-clip"])
        self.assertEqual(result["motion"], "pan_left")

    def test_rejects_empty_or_overlong_instructions_and_extreme_duration(self):
        for text in ("", "Create 90 seconds of video", "x" * 10001):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                compile_instructions(text, self.assets)


if __name__ == "__main__":
    unittest.main()
