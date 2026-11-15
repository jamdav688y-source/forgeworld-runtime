from __future__ import annotations

import unittest
from types import SimpleNamespace

from cognition import episode, presentation
from video_creation.production_adapter import project_from_package
from video_creation.project import ProjectError


class FakeBuilder:
    def __init__(self, status=episode.APPROVED):
        self.status = status
        self.candidate = SimpleNamespace(content_id="content-candidate-1")
        self.studio = SimpleNamespace(production_status=lambda candidate_id: {
            "status": self.status, "publication_authorized": False
        })
        self.exchange = SimpleNamespace(get_record=lambda record_id: self.candidate)
        scene = {"scene_id": "scene-001", "title": "Opening", "label": "DRAMATIZATION",
                 "audience": presentation.VIEWER, "source_refs": ["record-1"], "citations": ["source-1"],
                 "disclosures": ["This is a dramatization"], "narration_guidance": "", "narration_lines": [],
                 "on_screen_text": "Illustrative example", "transition": "Cut"}
        self.package = {"status": "DRAFT_PACKAGE", "publication_authorized": False,
                        "disclosures": {"contradictions": [], "unsupported_claims": [], "open_questions": []},
                        "presentation": {"contradiction_disclosures": []},
                        "lineage": {"candidate_id": "candidate-1", "candidate_content_id": "content-candidate-1",
                                    "contradiction_ids": [], "unsupported_claims": [], "open_questions": []},
                        "scenes": [scene], "youtube_description_draft": "Draft", "pinned_comment_draft": "Draft"}
        self.manifest = {"package_id": "package-1", "package_version": 2,
                         "lineage": {"candidate_id": "candidate-1", "candidate_content_id": "content-candidate-1"}}

    def load(self, package_id):
        return {"package": self.package, "manifest": self.manifest}


class ProductionAdapterTests(unittest.TestCase):
    def test_carries_labels_citations_and_lineage_into_project(self):
        builder = FakeBuilder()
        media_map = [{"scene_id": "scene-001", "asset_id": "asset-1", "duration_ms": 1000,
                      "source_in_ms": 0, "fit": "contain", "captions": []}]
        assets = [{"asset_id": "asset-1", "path": "a.png", "sha256": "a" * 64,
                   "kind": "image", "rights_status": "USER_PROVIDED"}]
        profile = {"width": 360, "height": 640, "fps_num": 30, "fps_den": 1,
                   "fit": "contain", "crf": 25}
        project = project_from_package(builder, "package-1", media_map, assets, profile, "episode-media")
        scene = project["scenes"][0]
        self.assertEqual(scene["label"], "DRAMATIZATION")
        self.assertEqual(scene["source_refs"], ["record-1"])
        self.assertEqual(scene["citations"], ["source-1"])
        self.assertEqual(project["lineage"]["candidate_content_id"], "content-candidate-1")
        self.assertFalse(project["lineage"]["publication_authorized"])

    def test_refuses_if_candidate_is_no_longer_approved(self):
        builder = FakeBuilder(status=episode.SUPERSEDED)
        media_map = [{"scene_id": "scene-001", "asset_id": "asset-1", "duration_ms": 1000,
                      "source_in_ms": 0, "fit": "contain", "captions": []}]
        assets = [{"asset_id": "asset-1", "path": "a.png", "sha256": "a" * 64,
                   "kind": "image", "rights_status": "USER_PROVIDED"}]
        profile = {"width": 360, "height": 640, "fps_num": 30, "fps_den": 1,
                   "fit": "contain", "crf": 25}
        with self.assertRaisesRegex(ProjectError, "not approved"):
            project_from_package(builder, "package-1", media_map, assets, profile, "episode-media")


if __name__ == "__main__":
    unittest.main()
