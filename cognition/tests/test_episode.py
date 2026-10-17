"""E1 episode candidate and production-review tests. Synthetic fixtures;
temporary stores; no network, publishing or platform access."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition import audience as au, contradiction, coordinator as co, cxp, cycle, episode as ep, exchange
from cognition import governor as gv
from cognition.tests import _events as ev
from cognition.tests.test_audience import item, video_observation, TOPIC
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_lenses import spies
from evidence_envelope import envelope

OPERATOR = "operator-founder"


class EpisodeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-e1-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = self.make(self.tmp / "a")
        self.x, self.g, self.runner, self.intake, self.studio = self.env
        self.artifact, self.question = self.completed_cycle(self.env)

    @staticmethod
    def make(root, lenses=None):
        x = exchange.CognitiveExchange(root / "store")
        g = gv.RecursionGovernor(x, root / "governor", gv.GovernorPolicy("policy-governor-v1", "operator-synthetic"))
        runner = cycle.CycleRunner(x, g, root / "artifacts", **({"lenses": lenses} if lenses else {}))
        return x, g, runner, au.AudienceIntake(x, root / "audience"), ep.EpisodeStudio(runner)

    @staticmethod
    def completed_cycle(env):
        x, g, runner, intake, studio = env
        root = runner.run([video_observation()], TOPIC, "2026-10-17T07:00:00Z")
        q = intake.import_batch("batch-yt-001", [item()], "2026-10-17T07:05:00Z")["results"][0]["record_id"]
        artifact = intake.research_cycle(runner, [q], TOPIC, "2026-10-17T08:00:00Z",
                                         parent_cycle_id=root["next_cycle"]["parent_cycle_id"])
        return artifact, q

    def draft(self):
        return self.studio.draft(self.artifact["artifact_id"], "2026-10-17T09:00:00Z")

    def acceptance(self, candidate_id):
        c = self.x.get_record(candidate_id).payload()
        return c["contradiction_ids"] + c["unsupported_claims"]

    def hand_built(self, mutate):
        """A candidate built outside the studio, from a correct draft's payload."""
        good = self.x.get_record(self.draft()).payload()
        payload = copy.deepcopy(good)
        mutate(payload)
        parents = sorted(set(payload["lens_output_ids"]) | set(payload["contradiction_ids"]) | set(payload["input_record_ids"]))
        return {"schema_version": 1, "kind": cxp.KIND_EPISODE_CANDIDATE, "representation": cxp.REP_DRAMATIZATION,
                "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
                "provenance": cxp.UNVERIFIED_INTERPRETATION, "privacy": cxp.PRIV_INTERNAL, "payload": payload,
                "sources": [], "derived_from": parents, "verification_ref": None, "consent_ref": None,
                "occurrence": {"emitter_id": "hand-built", "observed_at": "2026-10-17T09:30:00Z"}}

    def accept(self, raw):
        receipt = self.x.ingest(raw)
        self.assertEqual(receipt.status, exchange.ACCEPTED, (receipt.error_code, receipt.detail))
        return receipt.record_id

    def review_event(self, candidate_id, **overrides):
        event = {"schema_version": 1, "kind": cxp.KIND_EPISODE_REVIEW, "representation": cxp.REP_PARAPHRASE,
                 "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.HUMAN_ASSERTED,
                 "privacy": cxp.PRIV_INTERNAL,
                 "payload": {"candidate_id": candidate_id, "decision": ep.APPROVED, "reviewer": OPERATOR,
                             "accepted_uncertainties": [], "notes": None},
                 "sources": [], "derived_from": [candidate_id], "verification_ref": None, "consent_ref": None,
                 "occurrence": {"emitter_id": "forger", "observed_at": "2026-10-17T11:00:00Z"}}
        payload = overrides.pop("payload", {})
        event["payload"].update(payload)
        event.update(overrides)
        return event


class TestProductionPathway(EpisodeTestCase):
    def test_audience_question_to_reviewed_candidate(self):
        self.assertEqual(self.artifact["termination"], cycle.COMPLETED_WITH_CANDIDATES)
        cid = self.draft()
        record = self.x.get_record(cid)
        c = record.payload()
        self.assertEqual((record.representation, record.evidence, record.verification, record.provenance),
                         (cxp.REP_DRAMATIZATION, cxp.EV_NONE, cxp.VER_UNVERIFIED, cxp.UNVERIFIED_INTERPRETATION))
        self.assertEqual((c["cycle_id"], c["cycle_artifact_id"], c["assembly_id"]),
                         (self.artifact["governor_decision"]["cycle_id"], self.artifact["artifact_id"],
                          self.artifact["assembly"]["assembly_id"]))
        self.assertEqual(len(c["lens_output_ids"]), 7)
        self.assertEqual(c["audience_question_ids"], [self.question])
        self.assertEqual(c["contradiction_ids"], sorted(d["contradiction_id"] for d in self.artifact["preserved_disagreements"]))
        self.assertEqual(c["unsupported_claims"], sorted(self.artifact["assembly"]["unsupported_claims"]))
        self.assertEqual((c["revision"], c["supersedes"], c["dramatization_label"]), (1, None, ep.DRAMATIZATION_LABEL))
        self.assertEqual(self.studio.production_status(cid)["status"], ep.DRAFT)
        self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(cid))
        status = self.studio.production_status(cid)
        self.assertEqual((status["status"], status["production_preparation_authorized"], status["publication_authorized"]),
                         (ep.APPROVED, True, False))

    def test_acceptance_is_not_verification(self):
        cid = self.draft()
        self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(cid))
        for contradiction_id in self.x.get_record(cid).payload()["contradiction_ids"]:
            self.assertEqual(contradiction.assess(self.x, contradiction_id)["status"], contradiction.OPEN)
        self.assertEqual(self.x.get_record(cid).verification, cxp.VER_UNVERIFIED)
        self.assertEqual(self.x.get_record(self.question).verification, cxp.VER_UNVERIFIED)

    def test_approval_without_explicit_acceptance_is_refused(self):
        cid = self.draft()
        with self.assertRaises(ep.EpisodeError) as ctx:
            self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z")
        self.assertEqual(ctx.exception.reasons, [ep.R_UNCERTAINTY_NOT_ACCEPTED])
        c = self.x.get_record(cid).payload()
        with self.assertRaises(ep.EpisodeError):  # partial acceptance is not enough
            self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z",
                               accepted_uncertainties=c["contradiction_ids"])

    def test_needs_revision_and_rejection_take_precedence(self):
        cid = self.draft()
        self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(cid))
        self.studio.review(cid, ep.NEEDS_REVISION, "operator-editor", "2026-10-17T10:30:00Z", notes="Act 2 overstates.")
        self.assertEqual(self.studio.production_status(cid)["status"], ep.NEEDS_REVISION)
        self.studio.review(cid, ep.REJECTED, "operator-editor", "2026-10-17T11:00:00Z")
        self.assertEqual(self.studio.production_status(cid)["status"], ep.REJECTED)


class TestRefusedCandidates(EpisodeTestCase):
    def test_missing_contradiction_lineage_is_refused(self):
        omitted = self.accept(self.hand_built(lambda p: p["contradiction_ids"].pop()))
        problems = self.studio.approval_problems(omitted, self.acceptance(omitted))
        self.assertIn(ep.R_CONTRADICTION_OMITTED, problems)
        with self.assertRaises(ep.EpisodeError) as ctx:
            self.studio.review(omitted, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z",
                               accepted_uncertainties=self.acceptance(omitted))
        self.assertIn(ep.R_CONTRADICTION_OMITTED, ctx.exception.reasons)
        self.assertEqual(self.studio.production_status(omitted)["status"], ep.DRAFT)

    def test_incomplete_or_refused_cycles_cannot_be_drafted(self):
        duplicate = self.runner.run([], TOPIC, "2026-10-18T08:00:00Z", extra_input_ids=[self.question],
                                    parent_cycle_id=self.artifact["parent_cycle_id"])
        self.assertEqual(duplicate["termination"], cycle.REFUSED)
        with self.assertRaises(ep.EpisodeError) as ctx:
            self.studio.draft(duplicate["artifact_id"], "2026-10-18T09:00:00Z")
        self.assertEqual(ctx.exception.reasons, [ep.R_CYCLE_INCOMPLETE])

    def test_partial_lens_cycles_are_incomplete(self):
        def broken(brief):
            raise RuntimeError("synthetic lens failure")
        env = self.make(self.tmp / "partial", lenses=spies(MUSE=broken))
        artifact, _ = self.completed_cycle(env)
        self.assertEqual(artifact["termination"], cycle.COMPLETED_PARTIAL)
        with self.assertRaises(ep.EpisodeError) as ctx:
            env[4].draft(artifact["artifact_id"], "2026-10-17T09:00:00Z")
        self.assertEqual(ctx.exception.reasons, [ep.R_CYCLE_INCOMPLETE])

    def test_missing_or_mismatched_assembly_references(self):
        with self.assertRaises(ep.EpisodeError) as ctx:
            self.studio.draft("cxp-art-" + "0" * 64, "2026-10-17T09:00:00Z")
        self.assertEqual(ctx.exception.reasons, [ep.R_ARTIFACT_INVALID])
        def disputed(p):
            return {c for cid in p["contradiction_ids"] for c in self.x.record_metadata(cid)["contradiction_claims"]}
        # dropping a lens a contradiction is built on is refused outright at ingest...
        self.assertEqual(self.x.ingest(self.hand_built(
            lambda p: p["lens_output_ids"].remove(sorted(disputed(p))[0]))).error_code, cxp.E_TRANSITION_REFUSED)
        # ...dropping an undisputed lens is ingestible but can never be approved
        lens_dropped = self.accept(self.hand_built(
            lambda p: p["lens_output_ids"].remove(sorted(set(p["lens_output_ids"]) - disputed(p))[0])))
        self.assertIn(ep.R_LENS_SET_MISMATCH, self.studio.approval_problems(lens_dropped, self.acceptance(lens_dropped)))
        wrong_assembly = self.accept(self.hand_built(lambda p: p.update(assembly_id="cxp-asm-" + "1" * 64)))
        self.assertIn(ep.R_ASSEMBLY_MISMATCH, self.studio.approval_problems(wrong_assembly, self.acceptance(wrong_assembly)))
        unknown_artifact = self.accept(self.hand_built(lambda p: p.update(cycle_artifact_id="cxp-art-" + "2" * 64)))
        self.assertIn(ep.R_ARTIFACT_INVALID, self.studio.approval_problems(unknown_artifact))

    def test_structurally_false_lineage_is_refused_at_ingest(self):
        cases = {
            "observation posing as a lens output": (lambda p: p.update(lens_output_ids=sorted(p["lens_output_ids"][:-1] + [self.question])),
                                                    cxp.E_TRANSITION_REFUSED),
            "unmotivated audience question": (lambda p: p.update(audience_question_ids=[]), cxp.E_TRANSITION_REFUSED),
            "lens output posing as a contradiction": (lambda p: p.update(contradiction_ids=sorted(p["contradiction_ids"][:-1] + [p["lens_output_ids"][0]])),
                                                      cxp.E_TRANSITION_REFUSED),
            "malformed cycle id": (lambda p: p.update(cycle_id="cycle-1"), cxp.E_MALFORMED),
            "missing title": (lambda p: p.update(working_title=""), cxp.E_MALFORMED),
            "custom disclaimer": (lambda p: p.update(dramatization_label="Based on a true story"), cxp.E_MALFORMED),
        }
        for name, (mutate, code) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.x.ingest(self.hand_built(mutate)).error_code, code)

    def test_unsupported_claims_stay_disclosed(self):
        dropped = self.accept(self.hand_built(lambda p: p.update(unsupported_claims=p["unsupported_claims"][1:])))
        self.assertIn(ep.R_UNSUPPORTED_OMITTED, self.studio.approval_problems(dropped, self.acceptance(dropped)))
        cid = self.draft()
        acts = copy.deepcopy(self.x.get_record(cid).payload()["acts"])
        acts[-1]["text"] = "Resolution: it is a proven fact that the receiver refused the grant."
        overstated = self.studio.revise(cid, "2026-10-17T09:30:00Z", acts=acts)
        self.assertIn(ep.R_PRESENTED_AS_VERIFIED, self.studio.approval_problems(overstated, self.acceptance(overstated)))


class TestIntegrityAndReview(EpisodeTestCase):
    def test_altered_candidate_content_fails_closed(self):
        cid = self.draft()
        self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(cid))
        path = self.tmp / "a" / "store" / "payloads" / f"{cid}.json"
        tampered = json.loads(path.read_text())
        tampered["working_title"] = "We Proved an AI Cannot Give Itself Permission"
        path.write_text(json.dumps(tampered))
        with self.assertRaises(envelope.LedgerIntegrityError):
            self.studio.production_status(cid)

    def test_altered_artifact_voids_a_prior_approval(self):
        cid = self.draft()
        self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(cid))
        path = self.tmp / "a" / "artifacts" / f"{self.artifact['artifact_id']}.json"
        altered = json.loads(path.read_text())
        altered["preserved_disagreements"] = []
        path.write_text(json.dumps(altered))
        status = self.studio.production_status(cid)
        self.assertEqual(status["status"], ep.DRAFT)
        self.assertEqual(status["reviews"][0]["problems"], [ep.R_ARTIFACT_INVALID])

    def test_forged_reviews(self):
        cid = self.draft()
        with self.assertRaises(ep.EpisodeError):
            self.studio.review(cid, ep.APPROVED, "lens-muse", "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(cid))
        refused = {
            "model-authored": (self.review_event(cid, provenance=cxp.UNVERIFIED_INTERPRETATION), cxp.E_KIND_RULE),
            "component reviewer": (self.review_event(cid, payload={"reviewer": "coordinator"}), cxp.E_MALFORMED),
            "review claims verification": (self.review_event(cid, evidence=cxp.EV_SINGLE_SOURCE), cxp.E_KIND_RULE),
            "reviews a non-candidate": (self.review_event(self.question), cxp.E_TRANSITION_REFUSED),
        }
        for name, (raw, code) in refused.items():
            with self.subTest(name):
                self.assertEqual(self.x.ingest(raw).error_code, code)
        # a well-formed but unjustified approval written straight to the exchange counts for nothing
        self.accept(self.review_event(cid))
        status = self.studio.production_status(cid)
        self.assertEqual(status["status"], ep.DRAFT)
        self.assertEqual(status["reviews"][0]["problems"], [ep.R_UNCERTAINTY_NOT_ACCEPTED])

    def test_no_review_during_a_running_cycle(self):
        cid = self.draft()
        with self.g.running():
            with self.assertRaises(ep.EpisodeError) as ctx:
                self.studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(cid))
        self.assertEqual(ctx.exception.reasons, ["REVIEW_DURING_RUNNING_CYCLE"])

    def test_superseded_revisions_cannot_be_approved(self):
        v1 = self.draft()
        self.studio.review(v1, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z", accepted_uncertainties=self.acceptance(v1))
        v2 = self.studio.revise(v1, "2026-10-17T11:00:00Z", working_title="Can an AI Give Itself Permission?")
        self.assertEqual(self.x.get_record(v2).payload()["revision"], 2)
        self.assertEqual(self.x.get_record(v2).provenance, cxp.HUMAN_ASSERTED)
        self.assertEqual(self.studio.production_status(v1)["status"], ep.SUPERSEDED)
        self.assertEqual(self.studio.production_status(v2)["status"], ep.DRAFT)  # a revision needs its own review
        with self.assertRaises(ep.EpisodeError) as ctx:
            self.studio.review(v1, ep.APPROVED, OPERATOR, "2026-10-17T12:00:00Z", accepted_uncertainties=self.acceptance(v1))
        self.assertIn(ep.R_SUPERSEDED, ctx.exception.reasons)
        with self.assertRaises(ep.EpisodeError):  # one successor per revision
            self.studio.revise(v1, "2026-10-17T12:00:00Z", working_title="A competing branch")
        self.studio.review(v2, ep.APPROVED, OPERATOR, "2026-10-17T12:00:00Z", accepted_uncertainties=self.acceptance(v2))
        self.assertEqual(self.studio.production_status(v2)["status"], ep.APPROVED)


class TestBoundaries(EpisodeTestCase):
    def test_no_evidence_promotion(self):
        for overrides in ({"evidence": cxp.EV_SINGLE_SOURCE}, {"verification": cxp.VER_VERIFIED, "verification_ref": "cxp-rec-" + "3" * 64},
                          {"representation": cxp.REP_QUOTATION}, {"provenance": cxp.OBSERVED}):
            with self.subTest(overrides):
                raw = self.hand_built(lambda p: None)
                raw.update(overrides)
                self.assertIn(self.x.ingest(raw).error_code, (cxp.E_KIND_RULE, cxp.E_VERIFICATION_UNSUPPORTED))

    def test_no_recursive_self_ingestion(self):
        cid = self.draft()
        with self.assertRaises(co.CoordinatorError) as ctx:
            co.LensCoordinator(self.x).run([cid], TOPIC, "2026-10-18T00:00:00Z")
        self.assertEqual(ctx.exception.code, co.E_INPUT_KIND)
        candidate_event = self.hand_built(lambda p: p.update(working_title="Another title"))
        self.assertEqual(self.runner.run([candidate_event], TOPIC, "2026-10-18T00:00:00Z")["termination"],
                         cycle.SOURCE_REJECTED)
        echo = self.accept(ev.claim([cid], statement="The episode says the AI cannot permit itself.", evidence=cxp.EV_NONE))
        as_root = self.runner.run([], TOPIC, "2026-10-18T00:00:00Z", extra_input_ids=[echo])
        self.assertEqual((as_root["termination"], as_root["governor_decision"]["reason_code"]),
                         (cycle.AWAITING_HUMAN, gv.R_RECYCLED))
        as_child = self.runner.run([], TOPIC, "2026-10-18T00:00:00Z", extra_input_ids=[echo],
                                   parent_cycle_id=self.artifact["governor_decision"]["cycle_id"])
        self.assertEqual(as_child["detail"], gv.R_NO_NEW_EVIDENCE)
        lens_on_episode = {"schema_version": 1, "kind": cxp.KIND_LENS_OUTPUT, "representation": cxp.REP_INFERENCE,
                           "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
                           "provenance": cxp.UNVERIFIED_INTERPRETATION, "privacy": cxp.PRIV_INTERNAL,
                           "payload": {"lens_id": "MUSE", "lens_version": "9", "statement": "s", "positions": {},
                                       "uncertainties": [], "unsupported_claims": [], "next_action": None, "details": {}},
                           "sources": [], "derived_from": [cid], "verification_ref": None, "consent_ref": None,
                           "occurrence": {"emitter_id": "rogue", "observed_at": "2026-10-18T00:00:00Z"}}
        self.assertEqual(self.x.ingest(lens_on_episode).error_code, cxp.E_KIND_RULE)

    def test_no_publication_surface(self):
        self.assertFalse(self.studio.grants_execution_authority)
        for name in dir(ep.EpisodeStudio):
            for word in ("publish", "upload", "post", "schedule", "execute", "contact"):
                self.assertNotIn(word, name.lower())

    def test_deterministic_replay(self):
        def pipeline(root):
            env = self.make(root)
            artifact, _ = self.completed_cycle(env)
            studio = env[4]
            cid = studio.draft(artifact["artifact_id"], "2026-10-17T09:00:00Z")
            c = env[0].get_record(cid).payload()
            studio.review(cid, ep.APPROVED, OPERATOR, "2026-10-17T10:00:00Z",
                          accepted_uncertainties=c["contradiction_ids"] + c["unsupported_claims"])
            return cid, studio.production_status(cid), studio.audit(cid)
        self.assertEqual(pipeline(self.tmp / "one"), pipeline(self.tmp / "two"))
        self.assertEqual(snapshot(self.tmp / "one"), snapshot(self.tmp / "two"))
        cid = self.draft()
        self.assertEqual(self.draft(), cid)  # redrafting the same artifact is the same candidate


if __name__ == "__main__":
    unittest.main()
