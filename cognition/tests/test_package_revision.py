"""E3 governed producer editing tests. Synthetic fixtures; temporary
stores; no network, upload or platform access."""
import copy
import json
from pathlib import Path

from cognition import coordinator as co, contradiction, cxp, episode as ep, governor as gv
from cognition import package_revision as rv, presentation, production as pr
from cognition.tests import _events as ev
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_production import ProductionTestCase

EDITOR = "operator-producer"
T_EDIT, T_EDIT2 = "2026-10-18T09:00:00Z", "2026-10-18T10:00:00Z"


class RevisionTestCase(ProductionTestCase):
    def setUp(self):
        super().setUp()
        self.v1 = self.build()
        self.editor = rv.PackageEditor(self.builder)
        self.package = self.v1["package"]
        self.scene = {}
        for s in self.package["scenes"]:
            self.scene.setdefault(s["label"], s)
        self.internal = next(s for s in self.package["scenes"] if s["audience"] == presentation.INTERNAL_ONLY)

    def presentation_edits(self):
        act = self.scene[pr.DRAMATIZATION]
        ids = [s["scene_id"] for s in self.package["scenes"] if s["scene_id"] != self.internal["scene_id"]]
        return [
            {"op": "remove_scene", "scene_id": self.internal["scene_id"]},
            {"op": "reorder_scenes", "scene_ids": [ids[0], ids[-1]] + ids[1:-1]},
            {"op": "set_narration", "scene_id": act["scene_id"],
             "lines": ["In this reconstruction, imagine a system that could hand itself permission. What could go wrong?"]},
            {"op": "set_visual_prompts", "scene_id": act["scene_id"],
             "prompts": ["Soft-lit illustrative animation of two abstract devices; frame labelled DRAMATIZATION."]},
            {"op": "set_audio", "scene_id": act["scene_id"], "music": "single sustained synth note", "pacing": "brisk, 25 seconds"},
            {"op": "set_scene_text", "scene_id": act["scene_id"], "field": "transition", "value": "Hard cut on the padlock."},
            {"op": "set_viewer_questions", "questions": ["What would convince you a phone could not replay an old grant?",
                                                         "Which part of this would you want tested on camera?"]},
            {"op": "set_package_text", "field": "pinned_comment_draft",
             "value": "Which test would you want to see run next? Tell us below."},
        ]

    def revise(self, edits, package_id=None, editor=EDITOR, at=T_EDIT):
        return self.editor.revise(package_id or self.v1["package_id"], editor, edits, at)

    def refused(self, edits, expected, package_id=None):
        before = snapshot(self.tmp / "a")
        with self.assertRaises(rv.RevisionRefused) as ctx:
            self.revise(edits, package_id)
        self.assertTrue(any(expected in r for r in ctx.exception.reasons), ctx.exception.reasons)
        self.assertEqual(snapshot(self.tmp / "a"), before)  # nothing written
        return ctx.exception


class TestProducerWorkflow(RevisionTestCase):
    def test_edit_validate_review(self):
        v1_dir = Path(self.v1["directory"])
        v1_files = {p.name: p.read_bytes() for p in v1_dir.iterdir()}
        v2 = self.revise(self.presentation_edits())
        rev = v2["package"]["revision"]
        self.assertNotEqual(v2["package_id"], self.v1["package_id"])
        self.assertEqual((rev["package_revision"], rev["predecessor_package_id"], rev["predecessor_record_id"], rev["editor"]),
                         (2, self.v1["package_id"], self.v1["package_record_id"], EDITOR))
        self.assertEqual({c["class"] for c in rev["changes"]}, {rv.PRESENTATION_CHANGE})
        self.assertEqual(len(rev["changes"]), 8)
        self.assertEqual({p.name: p.read_bytes() for p in v1_dir.iterdir()}, v1_files)  # original untouched
        self.assertEqual(self.builder.load(v2["package_id"])["package"], v2["package"])
        self.assertEqual(pr.validate_package(v2["package"]), [])
        self.editor.review(v2["package_id"], ep.APPROVED, "operator-founder", T_EDIT2)
        status = self.editor.status(v2["package_id"])
        self.assertEqual((status["review_status"], status["locked_for_production_preparation"], status["publication_authorized"],
                          status["status"]), (ep.APPROVED, True, False, pr.DRAFT_PACKAGE))
        markdown = self.builder.load(v2["package_id"])["markdown"]
        self.assertIn(f"Package revision 2 by `{EDITOR}`", markdown)
        self.assertIn("Producer changes in this revision", markdown)

    def test_citations_labels_and_disclosures_survive(self):
        v2 = self.revise(self.presentation_edits())["package"]
        old = {s["scene_id"]: s for s in self.package["scenes"]}
        for s in v2["scenes"]:
            for field in ("label", "audience", "source_refs", "citations", "disclosures"):
                self.assertEqual(s[field], old[s["scene_id"]][field])
        for field in ("disclosures", "citation_sheet", "lineage", "experiment_references", "presentation"):
            self.assertEqual(v2[field], self.package[field])
        for cid in self.package["lineage"]["contradiction_ids"]:  # removed internal scene: still disclosed
            self.assertIn(cid, {d["contradiction_id"] for d in v2["disclosures"]["contradictions"]})
            self.assertEqual(contradiction.assess(self.x, cid)["status"], contradiction.OPEN)
        self.assertEqual([s["order"] for s in v2["scenes"]], list(range(1, len(v2["scenes"]) + 1)))

    def test_revision_chain_is_immutable_and_linear(self):
        v2 = self.revise(self.presentation_edits())
        v3 = self.revise([{"op": "set_package_text", "field": "thumbnail_concepts",
                           "value": ["An open padlock with a question mark, tag DRAMATIZATION"]}], v2["package_id"], at=T_EDIT2)
        self.assertEqual((v3["package"]["revision"]["package_revision"], v3["package"]["revision"]["predecessor_package_id"]),
                         (3, v2["package_id"]))
        for pid in (self.v1["package_id"], v2["package_id"], v3["package_id"]):
            self.builder.load(pid)  # every version still intact
        self.refused([{"op": "set_audio", "scene_id": self.scene[pr.DRAMATIZATION]["scene_id"], "music": "x", "pacing": "y"}],
                     rv.SUPERSEDED, package_id=self.v1["package_id"])
        # a hand-built branch off v1 is refused by the exchange as well
        record = self.x.get_record(v3["package_record_id"]).payload()
        branch = {"schema_version": 1, "kind": cxp.KIND_PRODUCTION_PACKAGE, "representation": cxp.REP_DRAMATIZATION,
                  "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.UNVERIFIED_INTERPRETATION,
                  "privacy": cxp.PRIV_INTERNAL,
                  "payload": {**record, "package_id": "cxp-pkg-" + "4" * 64, "package_revision": 2,
                              "predecessor_record_id": self.v1["package_record_id"],
                              "predecessor_package_id": self.v1["package_id"]},
                  "sources": [], "derived_from": sorted([record["candidate_id"], record["review_id"], self.v1["package_record_id"]]),
                  "verification_ref": None, "consent_ref": None,
                  "occurrence": {"emitter_id": "forger", "observed_at": T_EDIT2}}
        self.assertEqual(self.x.ingest(branch).error_code, cxp.E_TRANSITION_REFUSED)

    def test_deterministic_package_identifiers(self):
        v2 = self.revise(self.presentation_edits())
        other = self.make(self.tmp / "b")
        artifact, _ = self.completed_cycle(other)
        studio = other[4]
        cid = studio.draft(artifact["artifact_id"], "2026-10-17T09:00:00Z")
        c = other[0].get_record(cid).payload()
        studio.review(cid, ep.APPROVED, "operator-founder", "2026-10-17T10:00:00Z",
                      accepted_uncertainties=c["contradiction_ids"] + c["unsupported_claims"])
        builder = pr.PackageBuilder(studio, self.tmp / "b" / "packages")
        self.assertEqual(builder.build(cid, "2026-10-17T11:00:00Z")["package_id"], self.v1["package_id"])
        again = rv.PackageEditor(builder).revise(self.v1["package_id"], EDITOR, self.presentation_edits(), T_EDIT)
        self.assertEqual(again["package_id"], v2["package_id"])
        self.assertEqual(snapshot(self.tmp / "a" / "packages"), snapshot(self.tmp / "b" / "packages"))


class TestClassification(RevisionTestCase):
    def test_hypothesis_turned_into_verified_claim_is_refused(self):
        hyp = self.scene[pr.HYPOTHESIS]["scene_id"]
        exc = self.refused([{"op": "set_narration", "scene_id": hyp,
                             "lines": ["We verified that replaying an expired grant is always refused."]}],
                           "CLAIM_CHANGE:VERIFICATION_LANGUAGE")
        self.assertIn("RETURN_TO_EPISODE_CANDIDATE_REVISION_AND_HUMAN_REVIEW", exc.reasons)

    def test_claim_changes(self):
        act, hyp, quote = (self.scene[label]["scene_id"] for label in (pr.DRAMATIZATION, pr.HYPOTHESIS, pr.QUOTED_SOURCE))
        cases = {
            "QUOTATION_ALTERED": {"op": "set_narration", "scene_id": quote, "lines": ["Can phones replay grants?"]},
            "HYPOTHESIS_STATED_AS_RESULT": {"op": "set_narration", "scene_id": hyp,
                                            "lines": ["Replaying an expired grant is refused every time."]},
            "CERTAINTY_STRENGTHENED": {"op": "set_scene_text", "scene_id": act, "field": "transition",
                                       "value": "This clearly demonstrates the receiver is in control."},
            "UNCERTAINTY_REMOVED": {"op": "set_scene_text", "scene_id": act, "field": "on_screen_text",
                                    "value": "What happens inside ForgeWorld"},
            "DRAMATIZATION_PRESENTED_AS_FACT": {"op": "set_scene_text", "scene_id": act, "field": "narration_guidance",
                                                "value": "Narrate as real footage of events. This really happened."},
            "DRAMATIZATION_LABEL_REMOVED": {"op": "set_visual_prompts", "scene_id": act, "prompts": ["A sleek animation."]},
            "REMOVES_VIEWER_FACING_SCENE": {"op": "remove_scene", "scene_id": act},
            "DISCLOSURE_REMOVED": {"op": "set_package_text", "field": "youtube_description_draft",
                                   "value": "Watch how an AI refuses to give itself permission."},
            "VERIFICATION_LANGUAGE": {"op": "set_package_text", "field": "episode_title",
                                      "value": "Proven: An AI That Cannot Give Itself Permission"},
        }
        for reason, edit in cases.items():
            with self.subTest(reason):
                self.assertEqual((rv.classify(self.package, edit)["class"], rv.classify(self.package, edit)["reason"]),
                                 (rv.CLAIM_CHANGE, reason))

    def test_ambiguous_edits_fail_closed(self):
        interp = self.internal["scene_id"]
        act = self.scene[pr.DRAMATIZATION]["scene_id"]
        cases = {
            "LENS_STATEMENT_REWORDING": {"op": "set_narration", "scene_id": interp, "lines": ["The lenses mostly agree."]},
            "FIELD_NOT_EDITABLE": {"op": "set_scene_text", "scene_id": act, "field": "citations", "value": "x"},
            "UNRECOGNISED_EDIT": {"op": "set_label", "scene_id": act, "label": "QUOTED_SOURCE"},
            "UNKNOWN_SCENE": {"op": "set_audio", "scene_id": "scene-99-x", "music": "m", "pacing": "p"},
            "NOT_A_PERMUTATION": {"op": "reorder_scenes", "scene_ids": [act]},
            "NOT_A_QUESTION": {"op": "set_viewer_questions", "questions": ["Tell us what you think."]},
            "METHODOLOGY_NOTE_AS_VIEWER_QUESTION": {"op": "set_viewer_questions",
                                                    "questions": ["Was this estimated from a word list?"]},
        }
        for reason, edit in cases.items():
            with self.subTest(reason):
                self.assertEqual((rv.classify(self.package, edit)["class"], rv.classify(self.package, edit)["reason"]),
                                 (rv.AMBIGUOUS, reason))
        self.assertEqual(rv.classify(self.package, {"op": "set_package_text", "field": "disclosures", "value": {}})["reason"],
                         "FIELD_NOT_EDITABLE")

    def test_one_bad_edit_refuses_the_whole_revision(self):
        edits = self.presentation_edits() + [{"op": "set_package_text", "field": "episode_title",
                                              "value": "Confirmed: The AI That Cannot Give Itself Permission"}]
        exc = self.refused(edits, "CLAIM_CHANGE:VERIFICATION_LANGUAGE")
        self.assertEqual(len(exc.classifications), 9)

    def test_preservation_check_catches_direct_tampering(self):
        tampered = copy.deepcopy(self.package)
        tampered["scenes"][0]["citations"] = []
        tampered["disclosures"]["unsupported_claims"] = []
        problems = rv.preservation_problems(self.package, tampered)
        self.assertIn("FROZEN_FIELD_CHANGED:disclosures", problems)
        self.assertTrue(any(p.endswith(".citations") for p in problems))


class TestApprovalAndAuthority(RevisionTestCase):
    def test_revision_invalidates_package_approval(self):
        self.editor.review(self.v1["package_id"], ep.APPROVED, "operator-founder", T_EDIT)
        self.assertEqual(self.editor.status(self.v1["package_id"])["review_status"], ep.APPROVED)
        v2 = self.revise(self.presentation_edits(), at=T_EDIT2)
        self.assertEqual(self.editor.status(self.v1["package_id"])["review_status"], rv.SUPERSEDED)
        self.assertEqual(self.editor.status(v2["package_id"])["review_status"], rv.DRAFT)
        with self.assertRaises(rv.RevisionRefused) as ctx:
            self.editor.review(self.v1["package_id"], ep.APPROVED, "operator-founder", T_EDIT2)
        self.assertIn(rv.SUPERSEDED, ctx.exception.reasons)

    def test_withdrawn_candidate_approval_blocks_editing_and_voids_package_approval(self):
        v2 = self.revise(self.presentation_edits())
        self.editor.review(v2["package_id"], ep.APPROVED, "operator-founder", T_EDIT2)
        self.studio.review(self.candidate, ep.NEEDS_REVISION, "operator-editor", "2026-10-18T11:00:00Z")
        status = self.editor.status(v2["package_id"])
        self.assertEqual(status["review_status"], rv.DRAFT)
        self.assertIn(pr.P_NOT_APPROVED, status["reviews"][0]["problems"])
        with self.assertRaises(pr.PackageError):
            self.revise([{"op": "set_audio", "scene_id": self.scene[pr.DRAMATIZATION]["scene_id"], "music": "m", "pacing": "p"}],
                        v2["package_id"], at="2026-10-18T12:00:00Z")

    def test_unauthorized_editors_and_reviewers(self):
        edits = self.presentation_edits()
        for person in ("lens-muse", "coordinator", "Jane Producer", None, "episode-studio"):
            with self.subTest(person):
                with self.assertRaises(rv.RevisionRefused):
                    self.revise(edits, editor=person)
                with self.assertRaises(rv.RevisionRefused):
                    self.editor.review(self.v1["package_id"], ep.APPROVED, person, T_EDIT)
        with self.g.running():
            with self.assertRaises(rv.RevisionRefused) as ctx:
                self.revise(edits)
        self.assertEqual(ctx.exception.reasons, ["EDITOR_DURING_RUNNING_CYCLE"])

    def test_tampered_predecessor_cannot_be_revised(self):
        path = Path(self.v1["directory"]) / "package.json"
        data = json.loads(path.read_text())
        data["episode_title"] = "Edited by hand"
        path.write_bytes(cxp.canonical_bytes(data))
        with self.assertRaises(pr.PackageError) as ctx:
            self.revise(self.presentation_edits())
        self.assertEqual(ctx.exception.reasons, [pr.P_TAMPERED])

    def test_no_evidence_promotion(self):
        v2 = self.revise(self.presentation_edits())
        record = self.x.get_record(v2["package_record_id"])
        self.assertEqual((record.representation, record.evidence, record.verification, record.provenance),
                         (cxp.REP_DRAMATIZATION, cxp.EV_NONE, cxp.VER_UNVERIFIED, cxp.UNVERIFIED_INTERPRETATION))
        review_id = self.editor.review(v2["package_id"], ep.APPROVED, "operator-founder", T_EDIT2)
        forged = {"schema_version": 1, "kind": cxp.KIND_PACKAGE_REVIEW, "representation": cxp.REP_PARAPHRASE,
                  "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.UNVERIFIED_INTERPRETATION,
                  "privacy": cxp.PRIV_INTERNAL,
                  "payload": {"package_record_id": v2["package_record_id"], "package_id": v2["package_id"],
                              "decision": ep.APPROVED, "reviewer": "operator-founder", "notes": None},
                  "sources": [], "derived_from": [v2["package_record_id"]], "verification_ref": None, "consent_ref": None,
                  "occurrence": {"emitter_id": "forger", "observed_at": T_EDIT2}}
        self.assertEqual(self.x.ingest(forged).error_code, cxp.E_KIND_RULE)
        mismatched = copy.deepcopy(forged)
        mismatched.update(provenance=cxp.HUMAN_ASSERTED)
        mismatched["payload"]["package_id"] = self.v1["package_id"]
        self.assertEqual(self.x.ingest(mismatched).error_code, cxp.E_TRANSITION_REFUSED)
        for cid in self.package["lineage"]["contradiction_ids"]:
            self.assertEqual(contradiction.assess(self.x, cid)["status"], contradiction.OPEN)
        self.assertEqual(self.x.get_record(review_id).verification, cxp.VER_UNVERIFIED)

    def test_revised_packages_are_never_research_input(self):
        v2 = self.revise(self.presentation_edits())
        review_id = self.editor.review(v2["package_id"], ep.APPROVED, "operator-founder", T_EDIT2)
        for rid in (v2["package_record_id"], review_id):
            with self.assertRaises(co.CoordinatorError):
                co.LensCoordinator(self.x).run([rid], "t", "2026-10-19T00:00:00Z")
        echo = self.accept(ev.claim([review_id], statement="The producer approved it, so it must be true.", evidence=cxp.EV_NONE))
        self.assertEqual(self.runner.run([], "t", "2026-10-19T00:00:00Z", extra_input_ids=[echo])["governor_decision"]["reason_code"],
                         gv.R_RECYCLED)

    def test_no_publication_surface(self):
        v2 = self.revise(self.presentation_edits())
        for target in (v2["package"], v2["manifest"], self.x.get_record(v2["package_record_id"]).payload(),
                       self.editor.status(v2["package_id"])):
            self.assertIs(target["publication_authorized"], False)
        for obj in (rv.PackageEditor, rv):
            for name in dir(obj):
                for word in ("publish", "upload", "schedule", "send", "authenticate", "oauth"):
                    self.assertNotIn(word, name.lower(), name)
        self.assertFalse(self.editor.grants_execution_authority)
