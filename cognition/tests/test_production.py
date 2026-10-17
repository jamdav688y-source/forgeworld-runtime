"""E2 production package tests. Synthetic fixtures; temporary stores; no
network, upload, scheduling or platform access."""
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition import coordinator as co, cxp, cycle, episode as ep, exchange, governor as gv, production as pr
from cognition.tests import _events as ev
from cognition.tests.test_episode import EpisodeTestCase, OPERATOR
from cognition.tests.test_exchange import snapshot

T_BUILD = "2026-10-17T11:00:00Z"
TWELVE_ELEMENTS = ("episode_title", "intended_audience", "scenes", "citation_sheet", "disclosures",
                   "experiment_references", "audio_plan", "thumbnail_concepts", "opening_hook_concepts",
                   "youtube_description_draft", "pinned_comment_draft", "future_intake_questions")


class ProductionTestCase(EpisodeTestCase):
    def setUp(self):
        super().setUp()
        self.candidate = self.draft()
        self.approve(self.candidate)
        self.builder = pr.PackageBuilder(self.studio, self.tmp / "a" / "packages")

    def approve(self, cid, at="2026-10-17T10:00:00Z"):
        return self.studio.review(cid, ep.APPROVED, OPERATOR, at, accepted_uncertainties=self.acceptance(cid))

    def build(self, cid=None, builder=None):
        return (builder or self.builder).build(cid or self.candidate, T_BUILD)

    def refused(self, reason, cid=None):
        with self.assertRaises(pr.PackageError) as ctx:
            self.build(cid)
        self.assertIn(reason, ctx.exception.reasons)


class TestCompletePackage(ProductionTestCase):
    def test_audience_question_to_production_package(self):
        out = self.build()
        package, manifest = out["package"], out["manifest"]
        for key in TWELVE_ELEMENTS:
            self.assertIn(key, package)
        self.assertEqual((package["status"], package["publication_authorized"], package["generated_media_exists"]),
                         (pr.DRAFT_PACKAGE, False, False))
        self.assertEqual((manifest["status"], manifest["publication_authorized"], manifest["generated_media_exists"]),
                         (pr.DRAFT_PACKAGE, False, False))
        self.assertEqual(manifest["approval"]["reviewer"], OPERATOR)
        self.assertTrue(manifest["approval"]["acceptance_is_not_verification"])
        c = self.x.get_record(self.candidate).payload()
        lineage_ids = {r["record_id"] for r in manifest["lineage"]["records"]}
        self.assertEqual(lineage_ids, set(c["input_record_ids"]) | set(c["lens_output_ids"]) | set(c["contradiction_ids"]))
        for r in manifest["lineage"]["records"]:
            self.assertEqual(r["content_id"], self.x.get_record(r["record_id"]).content_id)

    def test_every_scene_is_labelled_cited_and_instructed(self):
        package = self.build()["package"]
        ids = [s["scene_id"] for s in package["scenes"]]
        self.assertEqual(len(ids), len(set(ids)))
        for s in package["scenes"]:
            self.assertIn(s["label"], pr.SCENE_LABELS)
            self.assertTrue(s["source_refs"] and s["disclosures"] and s["shot_list"] and s["visual_generation_prompts"])
            self.assertIn("No footage, narration or imagery exists yet", s["production_instructions"])
        labels = [s["label"] for s in package["scenes"]]
        self.assertEqual(labels[0], pr.QUOTED_SOURCE)
        self.assertEqual(package["scenes"][0]["citations"], ["youtube:yt-comment-0001"])
        self.assertIn(pr.DRAMATIZATION, labels)
        self.assertIn(pr.INTERPRETATION, labels)
        self.assertEqual(labels[-1], pr.HYPOTHESIS)

    def test_cognitive_material_is_carried_not_regenerated(self):
        before = {m["record_id"] for m in self.x.all_record_metadata() if m["kind"] == cxp.KIND_LENS_OUTPUT}
        package = self.build()["package"]
        after = {m["record_id"] for m in self.x.all_record_metadata() if m["kind"] == cxp.KIND_LENS_OUTPUT}
        self.assertEqual(before, after)  # no lens re-run
        c = self.x.get_record(self.candidate).payload()
        self.assertEqual({d["contradiction_id"] for d in package["disclosures"]["contradictions"]}, set(c["contradiction_ids"]))
        self.assertEqual({d["status"] for d in package["disclosures"]["contradictions"]}, {"OPEN"})
        self.assertEqual({u["claim"] for u in package["disclosures"]["unsupported_claims"]}, set(c["unsupported_claims"]))
        self.assertEqual(package["disclosures"]["open_questions"], c["open_questions"])
        self.assertTrue(package["experiment_references"])
        self.assertEqual({e["evidence_status"] for e in package["experiment_references"]}, {"NOT_EVIDENCE"})
        self.assertIn("recycled cognition", package["governance"]["recursion"])

    def test_human_can_inspect_without_forgeworld(self):
        out = self.build()
        directory = Path(out["directory"])
        self.assertEqual(sorted(p.name for p in directory.iterdir()), ["manifest.json", "package.json", "package.md"])
        package = json.loads((directory / "package.json").read_text())   # plain stdlib json
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["files"]["package.json"], hashlib.sha256((directory / "package.json").read_bytes()).hexdigest())
        markdown = (directory / "package.md").read_text()
        self.assertIn(package["episode_title"], markdown)
        self.assertIn("publication authorized: **no**", markdown)
        for s in package["scenes"]:
            self.assertIn(s["scene_id"], markdown)
        for d in package["disclosures"]["contradictions"]:
            self.assertIn(d["contradiction_id"], markdown)
        self.assertIn("youtube:yt-comment-0001", markdown)


class TestApprovalRevalidation(ProductionTestCase):
    def test_no_approval(self):
        fresh = self.studio.revise(self.candidate, "2026-10-17T10:30:00Z", working_title="Who Holds the Grant?")
        self.refused(pr.P_NOT_APPROVED, fresh)

    def test_revoked_by_later_decisions_or_erasure(self):
        for decision in (ep.NEEDS_REVISION, ep.REJECTED):
            with self.subTest(decision):
                setup = ProductionTestCase(methodName="run")
                setup.setUp()
                self.addCleanup(shutil.rmtree, setup.tmp, ignore_errors=True)
                setup.studio.review(setup.candidate, decision, "operator-editor", "2026-10-17T10:30:00Z")
                with self.assertRaises(pr.PackageError) as ctx:
                    setup.build()
                self.assertIn(pr.P_NOT_APPROVED, ctx.exception.reasons)
        review = self.studio.production_status(self.candidate)["reviews"][0]["review_id"]
        self.x.erase(review, "synthetic-erasure")
        self.refused(pr.P_NOT_APPROVED)

    def test_approval_of_an_older_revision_does_not_carry_over(self):
        v2 = self.studio.revise(self.candidate, "2026-10-17T10:30:00Z", working_title="Who Holds the Grant?")
        with self.assertRaises(pr.PackageError) as ctx:
            self.build(self.candidate)
        self.assertIn(ep.R_SUPERSEDED, ctx.exception.reasons)
        self.refused(pr.P_NOT_APPROVED, v2)
        self.approve(v2, "2026-10-17T11:30:00Z")
        self.assertEqual(self.build(v2)["manifest"]["package_version"], 2)


class TestLineageAndSources(ProductionTestCase):
    def test_incomplete_lineage(self):
        c = self.x.get_record(self.candidate).payload()
        self.x.erase(c["lens_output_ids"][0], "synthetic-erasure")
        self.refused(pr.P_MISSING_SOURCE)

    def test_missing_input(self):
        self.x.erase(self.question, "synthetic-erasure")
        self.refused(pr.P_MISSING_SOURCE)

    def test_altered_sources(self):
        path = self.tmp / "a" / "store" / "payloads" / f"{self.question}.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "statement": "Rewritten question"}))
        self.refused(pr.P_ALTERED_SOURCE)

    def test_altered_candidate(self):
        path = self.tmp / "a" / "store" / "payloads" / f"{self.candidate}.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "working_title": "Proven: AI Cannot Self-Authorize"}))
        self.refused(pr.P_ALTERED_SOURCE)


class TestValidator(ProductionTestCase):
    def setUp(self):
        super().setUp()
        self.package = self.build()["package"]
        self.assertEqual(pr.validate_package(self.package), [])

    def broken(self, mutate):
        p = copy.deepcopy(self.package)
        mutate(p)
        return pr.validate_package(p)

    def test_suppressed_contradictions(self):
        self.assertIn(pr.P_CONTRADICTION_SUPPRESSED, self.broken(lambda p: p["disclosures"].update(contradictions=[])))
        self.assertIn(pr.P_CONTRADICTION_SUPPRESSED, self.broken(
            lambda p: p.update(scenes=[s for s in p["scenes"] if s["label"] != pr.INTERPRETATION])))

    def test_unsupported_claims_presented_as_verified(self):
        def proven(p):
            p["scenes"][1]["narration_lines"] = ["It is a proven fact that the receiver refused the grant."]
        self.assertIn(pr.P_PRESENTED_AS_VERIFIED, self.broken(proven))
        self.assertIn(pr.P_PRESENTED_AS_VERIFIED, self.broken(lambda p: p.update(youtube_description_draft="Confirmed by tests.")))
        self.assertIn(pr.P_UNSUPPORTED_UNDISCLOSED, self.broken(lambda p: p["disclosures"].update(unsupported_claims=[])))
        self.assertIn(pr.P_OPEN_QUESTION_UNDISCLOSED, self.broken(lambda p: p["disclosures"].update(open_questions=[])))

    def test_uncited_or_unlabelled_scenes(self):
        self.assertIn(pr.P_UNCITED_SCENE, self.broken(lambda p: p["scenes"][0].update(source_refs=[])))
        self.assertIn(pr.P_BAD_LABEL, self.broken(lambda p: p["scenes"][0].update(label="FACT")))

    def test_publication_flag(self):
        self.assertIn(pr.P_PUBLICATION_FLAG, self.broken(lambda p: p.update(publication_authorized=True)))
        self.assertIn(pr.P_PUBLICATION_FLAG, self.broken(lambda p: p.update(status="PUBLISHED")))


class TestTamperingAndDeterminism(ProductionTestCase):
    def setUp(self):
        super().setUp()
        self.out = self.build()
        self.directory = Path(self.out["directory"])

    def assert_tampered(self):
        with self.assertRaises(pr.PackageError) as ctx:
            self.builder.load(self.out["package_id"])
        self.assertIn(pr.P_TAMPERED, ctx.exception.reasons)

    def rewrite(self, name, mutate):
        path = self.directory / name
        data = json.loads(path.read_text())
        mutate(data)
        path.write_bytes(cxp.canonical_bytes(data))

    def test_load_round_trip(self):
        loaded = self.builder.load(self.out["package_id"])
        self.assertEqual(loaded["package"], self.out["package"])

    def test_tampered_package_file(self):
        self.rewrite("package.json", lambda p: p.update(publication_authorized=True))
        self.assert_tampered()

    def test_tampered_manifest(self):
        self.rewrite("manifest.json", lambda m: m.update(publication_authorized=True))
        self.assert_tampered()

    def test_tampered_markdown(self):
        (self.directory / "package.md").write_text("# Edited\nPublished!\n")
        self.assert_tampered()

    def test_fully_rehashed_forgery_is_caught_by_the_cxp_anchor(self):
        package = json.loads((self.directory / "package.json").read_text())
        package["disclosures"]["unsupported_claims"] = package["disclosures"]["unsupported_claims"]  # same validity...
        package["pinned_comment_draft"] = "Subscribe!"                                                 # ...different content
        new_bytes = cxp.canonical_bytes(package)
        new_id = cxp.digest_id("package", package)
        forged_dir = self.directory.parent / new_id
        forged_dir.mkdir()
        (forged_dir / "package.json").write_bytes(new_bytes)
        md = (self.directory / "package.md").read_bytes()
        (forged_dir / "package.md").write_bytes(md)
        manifest = json.loads((self.directory / "manifest.json").read_text())
        manifest.update(package_id=new_id, files={"package.json": hashlib.sha256(new_bytes).hexdigest(),
                                                  "package.md": hashlib.sha256(md).hexdigest()})
        (forged_dir / "manifest.json").write_bytes(cxp.canonical_bytes(manifest))
        with self.assertRaises(pr.PackageError) as ctx:
            self.builder.load(new_id)
        self.assertEqual(ctx.exception.reasons, [pr.P_TAMPERED])

    def test_rebuild_is_identical_and_idempotent(self):
        before = snapshot(self.tmp / "a")
        again = self.build()
        self.assertEqual(again["package_id"], self.out["package_id"])
        self.assertEqual(snapshot(self.tmp / "a"), before)

    def test_independent_pipelines_produce_identical_packages(self):
        env = self.make(self.tmp / "b")
        artifact, _ = self.completed_cycle(env)
        studio = env[4]
        cid = studio.draft(artifact["artifact_id"], "2026-10-17T09:00:00Z")
        c = env[0].get_record(cid).payload()
        studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z",
                      accepted_uncertainties=c["contradiction_ids"] + c["unsupported_claims"])
        other = pr.PackageBuilder(studio, self.tmp / "b" / "packages").build(cid, T_BUILD)
        self.assertEqual(other["package_id"], self.out["package_id"])
        self.assertEqual(snapshot(self.tmp / "a" / "packages"), snapshot(self.tmp / "b" / "packages"))


class TestBoundaries(ProductionTestCase):
    def setUp(self):
        super().setUp()
        self.out = self.build()
        self.record = self.out["package_record_id"]

    def test_package_is_never_research_evidence(self):
        with self.assertRaises(co.CoordinatorError) as ctx:
            co.LensCoordinator(self.x).run([self.record], "t", "2026-10-18T00:00:00Z")
        self.assertEqual(ctx.exception.code, co.E_INPUT_KIND)
        echo = self.accept(ev.claim([self.record], statement="The package says grants are receiver-held.", evidence=cxp.EV_NONE))
        as_root = self.runner.run([], "t", "2026-10-18T00:00:00Z", extra_input_ids=[echo])
        self.assertEqual(as_root["governor_decision"]["reason_code"], gv.R_RECYCLED)
        as_child = self.runner.run([], "t", "2026-10-18T00:00:00Z", extra_input_ids=[echo],
                                   parent_cycle_id=self.artifact["governor_decision"]["cycle_id"])
        self.assertEqual(as_child["detail"], gv.R_NO_NEW_EVIDENCE)

    def _record_event(self, **overrides):
        payload = self.x.get_record(self.record).payload()
        event = {"schema_version": 1, "kind": cxp.KIND_PRODUCTION_PACKAGE, "representation": cxp.REP_DRAMATIZATION,
                 "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
                 "provenance": cxp.UNVERIFIED_INTERPRETATION, "privacy": cxp.PRIV_INTERNAL,
                 "payload": {**payload, "package_id": "cxp-pkg-" + "9" * 64}, "sources": [],
                 "derived_from": sorted([payload["candidate_id"], payload["review_id"]]), "verification_ref": None,
                 "consent_ref": None, "occurrence": {"emitter_id": "forger", "observed_at": "2026-10-18T00:00:00Z"}}
        payload_overrides = overrides.pop("payload", {})
        event["payload"].update(payload_overrides)
        event.update(overrides)
        return event

    def test_no_evidence_promotion_or_publication_through_the_record(self):
        cases = {
            "evidence": (self._record_event(evidence=cxp.EV_SINGLE_SOURCE), cxp.E_KIND_RULE),
            "observed": (self._record_event(provenance=cxp.OBSERVED), cxp.E_KIND_RULE),
            "published": (self._record_event(payload={"status": "PUBLISHED"}), cxp.E_KIND_RULE),
            "authorized": (self._record_event(payload={"publication_authorized": True}), cxp.E_KIND_RULE),
        }
        for name, (raw, code) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.x.ingest(raw).error_code, code)

    def test_record_must_cite_an_approving_review(self):
        nr = self.studio.review(self.candidate, ep.NEEDS_REVISION, "operator-editor", "2026-10-17T12:00:00Z")
        payload = self.x.get_record(self.record).payload()
        raw = self._record_event(payload={"review_id": nr}, derived_from=sorted([payload["candidate_id"], nr]))
        self.assertEqual(self.x.ingest(raw).error_code, cxp.E_TRANSITION_REFUSED)

    def test_no_publishing_surface(self):
        for obj in (pr.PackageBuilder, pr):
            for name in dir(obj):
                for word in ("publish", "upload", "schedule", "post_", "send", "authenticate", "oauth", "message"):
                    self.assertNotIn(word, name.lower(), name)
        self.assertFalse(self.builder.grants_execution_authority)
        self.assertEqual(self.x.get_record(self.record).payload()["publication_authorized"], False)


if __name__ == "__main__":
    unittest.main()
