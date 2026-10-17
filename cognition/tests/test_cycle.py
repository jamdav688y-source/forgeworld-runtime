"""Vertical slice: one authorized source through CXP, evidence
classification, R4 admission, seven lenses, preserved contradictions,
research candidates, a content-addressed durable artifact and an explicit
termination reason. Offline; temporary stores; synthetic fixtures plus the
real Phase 0 commit subject."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition import commerce, cxp, cycle, exchange, governor as gv, synthetic
from cognition.tests import _events as ev
from cognition.tests._commerce_events import signal
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_lenses import spies

TOPIC = "Receiver-held authorization in ForgeWorld"
T1, T2 = "2026-10-17T04:00:00Z", "2026-10-17T05:00:00Z"


def bench_observation(label="b", statement="A self-signed grant was refused by the receiver on the bench."):
    return ev.observation(statement=statement, sources=[ev.source(f"synthetic://bench-log-{label}", source_type="test_run")])


class CycleTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-cycle-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.runner = self.make(self.tmp / "a")

    def make(self, root, lenses=None, **policy):
        x = exchange.CognitiveExchange(root / "store")
        g = gv.RecursionGovernor(x, root / "governor", gv.GovernorPolicy("policy-governor-v1", "operator-synthetic", **policy))
        kwargs = {"lenses": lenses} if lenses else {}
        return cycle.CycleRunner(x, g, root / "artifacts", **kwargs)

    def first_cycle(self, runner=None):
        return (runner or self.runner).run([synthetic.phase0_observation_event()], TOPIC, T1)


class TestCompleteCycle(CycleTestCase):
    def test_source_to_artifact(self):
        a = self.first_cycle()
        self.assertEqual(a["termination"], cycle.COMPLETED_WITH_CANDIDATES)
        self.assertEqual((a["governor_decision"]["decision"], a["governor_decision"]["committed"]), (gv.ADMIT, True))
        # evidence classified before lenses ran
        c = a["evidence_classification"][0]
        self.assertEqual((c["kind"], c["evidence"], c["verification"]), (cxp.KIND_OBSERVATION, cxp.EV_SINGLE_SOURCE, cxp.VER_UNVERIFIED))
        self.assertEqual(c["sources"][0]["locator"], synthetic.PHASE0_COMMIT)
        # seven lenses, contradictions preserved, not averaged
        self.assertEqual(sum(r["status"] == "PRODUCED" for r in a["lens_runs"]), 7)
        self.assertEqual(sorted(d["question"] for d in a["preserved_disagreements"]),
                         [cxp.Q_CLAIM_ESTABLISHED, cxp.Q_READY_FOR_EPISODE])
        self.assertEqual({d["status"] for d in a["preserved_disagreements"]}, {"OPEN"})
        # research candidates: proposals only
        types = sorted(c["type"] for c in a["research_candidates"])
        self.assertEqual(types, [cycle.CANDIDATE_EXPERIMENT] + [cycle.CANDIDATE_RESOLVE_CONTRADICTION] * 2)
        for cand in a["research_candidates"]:
            self.assertEqual((cand["status"], cand["evidence_status"]), ("PROPOSED", "NOT_EVIDENCE"))
            self.assertTrue(cand["requires_human_authorization"] and cand["requires_governor_admission"])
            self.assertTrue(cand["candidate_id"].startswith("cxp-cand-"))
        # explicit non-actions
        self.assertTrue(a["experiment_execution"].startswith("NOT_PERFORMED"))
        self.assertTrue(a["capability_promotion"].startswith("NOT_EVALUATED"))
        self.assertFalse(a["next_cycle"]["started_automatically"])
        self.assertFalse(a["grants_execution_authority"])

    def test_measurement_claims_nothing_it_cannot_support(self):
        m = self.first_cycle()["measurement"]
        self.assertIsNone(m["baseline"])
        self.assertIsNone(m["improvement_claim"])
        self.assertIsNone(m["human_corrections_required"])
        self.assertEqual((m["independent_origins"], m["contradictions_detected"], m["research_candidates"]), (1, 2, 3))
        self.assertEqual(m["usage"], {"lens_invocations": 7, "lens_failures": 0, "cost_units": 7,
                                      "cost_unit": "lens-invocation-units"})

    def test_artifact_is_durable_and_content_addressed(self):
        a = self.first_cycle()
        path = self.tmp / "a" / "artifacts" / f"{a['artifact_id']}.json"
        self.assertTrue(path.exists())
        self.assertEqual(self.runner.load(a["artifact_id"]), a)
        tampered = json.loads(path.read_text())
        tampered["termination"] = cycle.COMPLETED_NO_CANDIDATES
        path.write_text(json.dumps(tampered))
        with self.assertRaises(cycle.CycleArtifactError):
            self.runner.load(a["artifact_id"])

    def test_candidates_never_become_records(self):
        self.first_cycle()
        kinds = {m["kind"] for m in self.runner.exchange.all_record_metadata()}
        self.assertEqual(kinds, {cxp.KIND_OBSERVATION, cxp.KIND_LENS_OUTPUT, cxp.KIND_CONTRADICTION})

    def test_a_governed_follow_up_cycle_needs_a_new_origin(self):
        first = self.first_cycle()
        parent = first["next_cycle"]["parent_cycle_id"]
        child = self.runner.run([bench_observation()], TOPIC, T2, parent_cycle_id=parent)
        self.assertEqual(child["termination"], cycle.COMPLETED_WITH_CANDIDATES)
        self.assertEqual((child["governor_decision"]["depth"], child["parent_cycle_id"]), (1, parent))
        self.assertEqual(len(child["next_cycle"]["excluded_origins"]), 2)


class TestRefusalsAndRejections(CycleTestCase):
    def test_duplicate_cycle_ends_in_a_recorded_refusal(self):
        first = self.first_cycle()
        ls = spies()
        runner = cycle.CycleRunner(self.runner.exchange, self.runner.governor, self.tmp / "a" / "artifacts", lenses=ls)
        again = runner.run([synthetic.phase0_observation_event()], TOPIC, T2)
        self.assertEqual((again["termination"], again["detail"]), (cycle.REFUSED, gv.R_DUPLICATE))
        self.assertEqual(sum(s.calls for s in ls), 0)
        self.assertTrue((self.tmp / "a" / "artifacts" / f"{again['artifact_id']}.json").exists())
        self.assertEqual(runner.load(first["artifact_id"]), first)  # the original is untouched

    def test_same_origin_follow_up_is_refused_for_lack_of_new_evidence(self):
        parent = self.first_cycle()["next_cycle"]["parent_cycle_id"]
        same_origin = ev.observation(statement="Phase 0 also added issue-grant and revoke-grant commands.")
        child = self.runner.run([same_origin], TOPIC, T2, parent_cycle_id=parent)
        self.assertEqual((child["termination"], child["detail"]), (cycle.REFUSED, gv.R_NO_NEW_EVIDENCE))

    def test_a_thousand_reactions_are_one_lineage(self):
        first = self.first_cycle()
        obs = first["evidence_classification"][0]["record_id"]
        reactions = [self.runner.exchange.ingest(ev.claim([obs], statement=f"reaction {i}: this is huge",
                                                          representation=cxp.REP_PARAPHRASE)).record_id
                     for i in range(40)]
        parent = first["next_cycle"]["parent_cycle_id"]
        child = self.runner.run([], TOPIC, T2, parent_cycle_id=parent, extra_input_ids=reactions[:8])
        self.assertEqual((child["termination"], child["detail"]), (cycle.REFUSED, gv.R_NO_NEW_EVIDENCE))
        self.assertEqual({c["independent_origin_count"] for c in child["evidence_classification"]}, {1})
        flood = self.runner.run([], TOPIC, T2, parent_cycle_id=parent, extra_input_ids=reactions)
        self.assertEqual(flood["termination"], cycle.SOURCE_REJECTED)  # input budget stops it before governance
        self.assertIn("max_inputs", flood["detail"])

    def test_malformed_or_non_observation_sources_are_rejected_before_governance(self):
        before = snapshot(self.tmp / "a")
        malformed = synthetic.phase0_observation_event()
        malformed["schema_version"] = 2
        lead = signal(commerce.OPPORTUNITY_IDENTIFIED, summary="Owner asked about workflow losses.")
        lens_shaped = ev.claim(["cxp-rec-" + "0" * 64])
        for source, why in ((malformed, "SCHEMA_VERSION"), (lead, "OBSERVATION"), (lens_shaped, "OBSERVATION"), ("text", "OBSERVATION")):
            with self.subTest(why):
                a = self.runner.run([source], TOPIC, T1)
                self.assertEqual(a["termination"], cycle.SOURCE_REJECTED)
                self.assertNotIn("governor_decision", a)
        self.assertEqual(self.runner.governor.ledger_entries(), ())
        self.assertEqual(self.runner.exchange.all_record_metadata(), ())
        self.assertEqual(self.runner.run([], TOPIC, T1)["termination"], cycle.SOURCE_REJECTED)
        self.assertNotEqual(snapshot(self.tmp / "a"), before)  # ...but each rejection left an artifact

    def test_commercial_inputs_wait_for_a_human(self):
        lead = self.runner.exchange.ingest(signal(commerce.OPPORTUNITY_IDENTIFIED, summary="Owner asked about losses.")).record_id
        lead_claim = self.runner.exchange.ingest(ev.claim([lead], statement="This buyer may need a diagnostic.")).record_id
        held = self.runner.run([], TOPIC, T1, extra_input_ids=[lead_claim])
        self.assertEqual((held["termination"], held["governor_decision"]["reason_code"]), (cycle.AWAITING_HUMAN, gv.R_COMMERCIAL))
        approval = self.runner.governor.record_approval(held["governor_decision"]["cycle_id"], gv.R_COMMERCIAL, "operator-synthetic")
        done = self.runner.run([], TOPIC, T2, approval_id=approval, extra_input_ids=[lead_claim])
        self.assertIn(done["termination"], (cycle.COMPLETED_WITH_CANDIDATES, cycle.COMPLETED_NO_CANDIDATES))
        self.assertEqual(done["governor_decision"]["reason_code"], gv.R_APPROVED)

    def test_budget_exhaustion_terminates(self):
        runner = self.make(self.tmp / "small", max_lens_invocations=7, max_cost_units=7)
        parent = self.first_cycle(runner)["next_cycle"]["parent_cycle_id"]
        child = runner.run([bench_observation()], TOPIC, T2, parent_cycle_id=parent)
        self.assertEqual((child["termination"], child["detail"]), (cycle.REFUSED, gv.R_BUDGET))

    def test_lens_failures_give_a_partial_cycle(self):
        def broken(brief):
            raise RuntimeError("synthetic lens failure")
        runner = self.make(self.tmp / "partial", lenses=spies(STORYWEAVER=broken))
        a = self.first_cycle(runner)
        self.assertEqual(a["termination"], cycle.COMPLETED_PARTIAL)
        self.assertEqual(a["measurement"]["usage"]["lens_failures"], 1)
        self.assertEqual(a["measurement"]["lenses_available"], 6)


class TestDeterminismAndAuthority(CycleTestCase):
    def test_independent_runs_produce_identical_artifacts(self):
        a = self.first_cycle()
        b = self.first_cycle(self.make(self.tmp / "b"))
        self.assertEqual(a, b)
        self.assertEqual(snapshot(self.tmp / "a" / "artifacts"), snapshot(self.tmp / "b" / "artifacts"))

    def test_no_authority_bearing_surface(self):
        self.assertFalse(self.runner.grants_execution_authority)
        for name in dir(cycle.CycleRunner):
            for word in ("execute", "publish", "contact", "spend", "authorize", "promote", "approve"):
                self.assertNotIn(word, name.lower())

    def test_runner_requires_a_governor(self):
        with self.assertRaises(ValueError):
            cycle.CycleRunner(self.runner.exchange, None, self.tmp / "x")


if __name__ == "__main__":
    unittest.main()
