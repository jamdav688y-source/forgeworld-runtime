"""R4 Recursion Governor tests: cycle identity and lineage, duplicate and
concurrent admission, ancestry integrity, evidence novelty, recycled
content, budgets and failure limits, usage accounting, commercial
re-entry and human approval, coordinator integration, determinism and
authority. Local temporary stores only; threads (not processes or sockets)
for the concurrency test."""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from cognition import commerce, coordinator as co, cxp, exchange, governor as gv, lenses, synthetic
from cognition.tests import _events as ev
from cognition.tests._commerce_events import signal
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_lenses import Spy, spies

TOPIC = "Receiver-held authorization in ForgeWorld"
T = "2026-10-17T03:00:00Z"


def policy(**overrides):
    return gv.GovernorPolicy(**{"policy_id": "policy-governor-v1", "approved_by": "operator-synthetic", **overrides})


class GovernorTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-r4-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.x = exchange.CognitiveExchange(self.tmp / "store")
        self.g = gv.RecursionGovernor(self.x, self.tmp / "governor", policy())
        self.obs_a = self.accept(synthetic.phase0_observation_event())
        self.obs_b = self.accept(ev.observation(statement="The phone node refused a self-signed grant.",
                                                sources=[ev.source("synthetic://bench-log-b", source_type="test_run")]))
        self.obs_c = self.accept(ev.observation(statement="An expired grant was refused at the receiver.",
                                                sources=[ev.source("synthetic://bench-log-c", source_type="test_run")]))

    def accept(self, raw):
        receipt = self.x.ingest(raw)
        self.assertEqual(receipt.status, exchange.ACCEPTED, (receipt.error_code, receipt.detail))
        return receipt.record_id

    def coord(self, lens_list=None, g=None, budget=co.LensBudget()):
        return co.LensCoordinator(self.x, lens_list or lenses.LENSES, budget, governor=g or self.g)

    def run_cycle(self, inputs, parent=None, approval=None, lens_list=None, g=None):
        return self.coord(lens_list, g).run(inputs, TOPIC, T, parent_cycle_id=parent, approval_id=approval)

    def request(self, inputs, parent=None, approval=None, planned=7):
        return gv.CycleRequest(purpose=co.GOVERNED_PURPOSE, input_record_ids=tuple(inputs),
                               planned_lens_invocations=planned, parent_cycle_id=parent, approval_id=approval)

    def decision(self, report):
        return report["governor_decision"]


class TestDemonstration(GovernorTestCase):
    def test_admit_duplicate_novelty_and_commercial(self):
        # one admitted cycle
        first = self.run_cycle([self.obs_a])
        d = self.decision(first)
        self.assertEqual((d["decision"], d["reason_code"], d["committed"], d["depth"]), (gv.ADMIT, gv.R_ADMITTED, True, 0))
        self.assertEqual(d["root_cycle_id"], d["cycle_id"])
        self.assertEqual(sum(r["status"] == co.PRODUCED for r in first["lens_runs"]), 7)
        self.assertEqual(d["budget_remaining"]["lens_invocations"], 14)
        root = d["cycle_id"]
        # one duplicate refusal
        again = self.decision(self.run_cycle([self.obs_a]))
        self.assertEqual((again["decision"], again["reason_code"]), (gv.REFUSE, gv.R_DUPLICATE))
        # one evidence-novelty refusal: a paraphrase of the parent's evidence
        paraphrase = self.accept(ev.claim([self.obs_a], representation=cxp.REP_PARAPHRASE,
                                          statement="Execution needs a grant the receiver holds."))
        stale = self.decision(self.run_cycle([paraphrase], parent=root))
        self.assertEqual((stale["decision"], stale["reason_code"]), (gv.REFUSE, gv.R_NO_NEW_EVIDENCE))
        # one commercial human-approval requirement
        lead = self.accept(signal(commerce.OPPORTUNITY_IDENTIFIED, summary="Owner asked about workflow losses."))
        lead_claim = self.accept(ev.claim([lead], statement="This buyer may need a diagnostic."))
        held = self.run_cycle([lead_claim])
        self.assertEqual((self.decision(held)["decision"], self.decision(held)["reason_code"]), (gv.NEEDS_HUMAN, gv.R_COMMERCIAL))
        self.assertEqual(held["lens_runs"], [])
        self.assertEqual(self.decision(held)["evidence_refs"]["commercial_records"], [lead])


class TestIdentity(GovernorTestCase):
    def test_cycle_id_is_deterministic_and_parent_bound(self):
        one = self.g.evaluate(self.request([self.obs_a, self.obs_b]))
        two = self.g.evaluate(self.request([self.obs_b, self.obs_a, self.obs_a]))
        self.assertEqual(one.cycle_id, two.cycle_id)
        self.assertFalse(one.committed)
        self.assertFalse((self.tmp / "governor" / "governor.jsonl").exists())  # evaluate writes nothing
        contents = [self.x.record_metadata(r)["content_id"] for r in (self.obs_a, self.obs_b)]
        self.assertEqual(one.cycle_id, gv.cycle_id_for(co.GOVERNED_PURPOSE, contents, None))
        self.assertNotEqual(one.cycle_id, gv.cycle_id_for(co.GOVERNED_PURPOSE, contents, "cxp-cycle-" + "0" * 64))
        self.assertNotEqual(one.cycle_id, gv.cycle_id_for("other-purpose", contents, None))

    def test_child_inherits_root_and_depth(self):
        root = self.decision(self.run_cycle([self.obs_a]))["cycle_id"]
        child = self.decision(self.run_cycle([self.obs_b], parent=root))
        grandchild = self.decision(self.run_cycle([self.obs_c], parent=child["cycle_id"]))
        self.assertEqual([child["root_cycle_id"], grandchild["root_cycle_id"]], [root, root])
        self.assertEqual([child["depth"], grandchild["depth"]], [1, 2])
        self.assertEqual(grandchild["evidence_refs"]["ancestry"], [child["cycle_id"], root])

    def test_invalid_parents_are_refused(self):
        for parent in ("cxp-cycle-" + "a" * 64, "not-a-cycle", 42):
            with self.subTest(parent=parent):
                d = self.g.evaluate(self.request([self.obs_a], parent=parent))
                self.assertEqual((d.decision, d.reason_code), (gv.REFUSE, gv.R_INVALID_PARENT))
        unfinished = self.g.admit(self.request([self.obs_a]))
        d = self.g.evaluate(self.request([self.obs_b], parent=unfinished.cycle_id))
        self.assertEqual(d.reason_code, gv.R_PARENT_NOT_COMPLETED)

    def test_bad_requests_are_refused(self):
        self.x.erase(self.obs_c, "synthetic-erasure")
        cases = [(self.request([]), gv.R_INVALID_INPUT), (self.request(["cxp-rec-" + "b" * 64]), gv.R_INVALID_INPUT),
                 (self.request([self.obs_c]), gv.R_INPUT_ERASED), (self.request([self.obs_a], planned=0), gv.R_INVALID_INPUT),
                 (gv.CycleRequest("Bad Purpose", (self.obs_a,), 7), gv.R_INVALID_INPUT)]
        for request, code in cases:
            with self.subTest(code=code):
                self.assertEqual(self.g.evaluate(request).reason_code, code)


class TestDuplicatesAndConcurrency(GovernorTestCase):
    def test_duplicate_refusal_invokes_no_lens_and_writes_nothing(self):
        self.run_cycle([self.obs_a])
        before = snapshot(self.tmp)
        ls = spies()
        report = self.run_cycle([self.obs_a], lens_list=ls)
        self.assertEqual(self.decision(report)["reason_code"], gv.R_DUPLICATE)
        self.assertEqual(sum(s.calls for s in ls), 0)
        self.assertEqual(snapshot(self.tmp), before)

    def test_concurrent_admission_commits_exactly_once(self):
        governors = [gv.RecursionGovernor(self.x, self.tmp / "governor", policy()) for _ in range(8)]
        barrier, results = threading.Barrier(len(governors)), []

        def attempt(g):
            barrier.wait()
            results.append(g.admit(self.request([self.obs_a])))
        threads = [threading.Thread(target=attempt, args=(g,)) for g in governors]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        committed = [r for r in results if r.committed]
        self.assertEqual(len(committed), 1)
        self.assertEqual({r.reason_code for r in results if not r.committed}, {gv.R_DUPLICATE})
        admitted = [e for e in self.g.ledger_entries() if e["entry"] == "ADMITTED"]
        self.assertEqual(len(admitted), 1)


class TestLedgerIntegrity(GovernorTestCase):
    def _tamper(self, mutate):
        root = self.decision(self.run_cycle([self.obs_a]))["cycle_id"]
        self.run_cycle([self.obs_b], parent=root)
        path = self.tmp / "governor" / "governor.jsonl"
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        mutate(entries)
        path.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in entries))
        d = self.g.evaluate(self.request([self.obs_c], parent=root))
        self.assertEqual((d.decision, d.reason_code), (gv.REFUSE, gv.R_LEDGER))
        before = path.read_bytes()
        self.assertEqual(self.g.admit(self.request([self.obs_c], parent=root)).reason_code, gv.R_LEDGER)
        self.assertEqual(path.read_bytes(), before)

    def test_child_before_parent_is_an_ancestry_violation(self):
        self._tamper(lambda e: e.insert(0, e.pop(2)))

    def test_forged_cycle_identity(self):
        self._tamper(lambda e: e[0].update(input_content_ids=["cxp-content-" + "f" * 64]))

    def test_usage_beyond_reservation(self):
        self._tamper(lambda e: e[1].update(lens_invocations=99, cost_units=99))

    def test_second_completion(self):
        self._tamper(lambda e: e.append(dict(e[1])))

    def test_forged_approval_reference(self):
        self._tamper(lambda e: e[2].update(approval_id="cxp-approval-" + "c" * 64))

    def test_complete_refuses_bad_reports(self):
        d = self.g.admit(self.request([self.obs_a], planned=3))
        for args in ((d.cycle_id, 4, 0), (d.cycle_id, 2, 3), ("cxp-cycle-" + "0" * 64, 1, 0)):
            with self.subTest(args=args), self.assertRaises(gv.GovernorError):
                self.g.complete(*args)
        self.g.complete(d.cycle_id, 3, 1)
        with self.assertRaises(gv.GovernorError):
            self.g.complete(d.cycle_id, 3, 1)


class TestEvidenceNovelty(GovernorTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.decision(self.run_cycle([self.obs_a]))["cycle_id"]

    def assert_refused(self, inputs):
        d = self.decision(self.run_cycle(inputs, parent=self.root))
        self.assertEqual((d["decision"], d["reason_code"]), (gv.REFUSE, gv.R_NO_NEW_EVIDENCE), d["evidence_refs"])

    def test_transformations_add_no_evidence(self):
        for rep in (cxp.REP_PARAPHRASE, cxp.REP_INFERENCE, cxp.REP_DRAMATIZATION, cxp.REP_HYPOTHESIS):
            with self.subTest(rep):
                claim = self.accept(ev.claim([self.obs_a], representation=rep, statement=f"{rep} of the commit",
                                             evidence=cxp.EV_NONE))
                self.assert_refused([claim])

    def test_lens_outputs_and_contradictions_add_no_evidence(self):
        a = self.x.all_record_metadata()
        lens_rid = next(m["record_id"] for m in a if m["kind"] == cxp.KIND_LENS_OUTPUT and m["lens_id"] == "MUSE")
        recycled = self.accept(ev.claim([lens_rid], statement="The muse says this matters."))
        self.assert_refused([recycled])
        cmap = next(m["record_id"] for m in a if m["kind"] == cxp.KIND_CONTRADICTION)
        summary = self.accept(ev.claim([cmap], statement="The lenses disagree.", evidence=cxp.EV_NONE))
        self.assert_refused([summary])

    def test_a_new_record_of_an_already_used_origin_is_not_new_evidence(self):
        same_source = self.accept(ev.observation(statement="Phase 0 also added issue-grant and revoke-grant."))
        d = self.decision(self.run_cycle([same_source], parent=self.root))
        self.assertEqual(d["reason_code"], gv.R_NO_NEW_EVIDENCE)
        self.assertEqual(len(d["evidence_refs"]["new_observation_roots"]), 1)  # new record, but...
        self.assertEqual(d["evidence_refs"]["new_origins"], [])                 # ...no new origin

    def test_a_genuinely_new_source_is_admitted_alongside_old_material(self):
        paraphrase = self.accept(ev.claim([self.obs_a], representation=cxp.REP_PARAPHRASE, statement="restated"))
        d = self.decision(self.run_cycle([paraphrase, self.obs_b], parent=self.root))
        self.assertEqual((d["decision"], d["depth"]), (gv.ADMIT, 1))
        self.assertEqual(d["evidence_refs"]["new_observation_roots"], [self.obs_b])

    def test_novelty_is_measured_against_the_whole_ancestry(self):
        child = self.decision(self.run_cycle([self.obs_b], parent=self.root))["cycle_id"]
        d = self.decision(self.run_cycle([self.obs_a], parent=child))  # obs_a was used by the grandparent
        self.assertEqual(d["reason_code"], gv.R_NO_NEW_EVIDENCE)


class TestResourceGovernance(GovernorTestCase):
    def test_lens_budget_exhaustion(self):
        g = gv.RecursionGovernor(self.x, self.tmp / "g2", policy(max_lens_invocations=14, max_cost_units=14))
        root = self.decision(self.run_cycle([self.obs_a], g=g))["cycle_id"]
        child = self.decision(self.run_cycle([self.obs_b], parent=root, g=g))
        self.assertEqual(child["budget_remaining"]["lens_invocations"], 0)
        ls = spies()
        d = self.decision(self.run_cycle([self.obs_c], parent=child["cycle_id"], g=g, lens_list=ls))
        self.assertEqual((d["decision"], d["reason_code"]), (gv.REFUSE, gv.R_BUDGET))
        self.assertEqual(sum(s.calls for s in ls), 0)

    def test_cost_budget_uses_its_own_units(self):
        g = gv.RecursionGovernor(self.x, self.tmp / "g3", policy(cost_per_lens_invocation=5, max_cost_units=40))
        d = self.decision(self.run_cycle([self.obs_a], g=g))
        self.assertEqual(d["budget_remaining"]["cost_units"], 5)
        self.assertEqual(d["budget_remaining"]["cost_unit"], "lens-invocation-units")
        child = self.decision(self.run_cycle([self.obs_b], parent=d["cycle_id"], g=g))
        self.assertEqual(child["reason_code"], gv.R_BUDGET)

    def test_depth_limit(self):
        g = gv.RecursionGovernor(self.x, self.tmp / "g4", policy(max_depth=1))
        root = self.decision(self.run_cycle([self.obs_a], g=g))["cycle_id"]
        child = self.decision(self.run_cycle([self.obs_b], parent=root, g=g))["cycle_id"]
        self.assertEqual(self.decision(self.run_cycle([self.obs_c], parent=child, g=g))["reason_code"], gv.R_DEPTH)

    def test_repeated_failures_stop_the_lineage(self):
        def broken(brief):
            raise RuntimeError("synthetic lens failure")
        g = gv.RecursionGovernor(self.x, self.tmp / "g5", policy(max_failures=2))
        root = self.decision(self.run_cycle([self.obs_a], g=g, lens_list=spies(MUSE=broken, EMPATH=broken)))["cycle_id"]
        completed = [e for e in g.ledger_entries() if e["entry"] == "COMPLETED"][0]
        self.assertEqual((completed["lens_invocations"], completed["failures"]), (7, 2))
        self.assertEqual(self.decision(self.run_cycle([self.obs_b], parent=root, g=g))["reason_code"], gv.R_FAILURES)

    def test_unreported_usage_blocks_the_lineage(self):
        root = self.decision(self.run_cycle([self.obs_a]))["cycle_id"]
        self.g.admit(self.request([self.obs_b], parent=root))  # admitted, never completed
        d = self.g.evaluate(self.request([self.obs_c], parent=root))
        self.assertEqual((d.reason_code, d.evidence_refs["incomplete_cycles"] != []), (gv.R_UNACCOUNTED, True))

    def test_interrupted_run_still_reports_conservative_usage(self):
        class Abort(BaseException):
            pass

        def abort(brief):
            raise Abort()
        with self.assertRaises(Abort):
            self.run_cycle([self.obs_a], lens_list=spies(ARCHITECT=abort))
        completed = [e for e in self.g.ledger_entries() if e["entry"] == "COMPLETED"]
        self.assertEqual((completed[0]["lens_invocations"], completed[0]["failures"]), (3, 1))


class TestCommercialBoundaryAndApprovals(GovernorTestCase):
    def setUp(self):
        super().setUp()
        lead = self.accept(signal(commerce.OPPORTUNITY_IDENTIFIED, summary="Owner asked about workflow losses."))
        self.lead_claim = self.accept(ev.claim([lead], statement="This buyer may need a diagnostic."))

    def test_commercial_reentry_needs_a_matching_human_approval(self):
        held = self.decision(self.run_cycle([self.lead_claim]))
        cycle = held["cycle_id"]
        wrong_reason = self.g.record_approval(cycle, gv.R_RECYCLED, "operator-synthetic")
        other_cycle = self.g.record_approval("cxp-cycle-" + "d" * 64, gv.R_COMMERCIAL, "operator-synthetic")
        for approval in (None, wrong_reason, other_cycle, "cxp-approval-" + "e" * 64):
            with self.subTest(approval=approval):
                self.assertEqual(self.decision(self.run_cycle([self.lead_claim], approval=approval))["decision"],
                                 gv.NEEDS_HUMAN)
        good = self.g.record_approval(cycle, gv.R_COMMERCIAL, "operator-synthetic")
        report = self.run_cycle([self.lead_claim], approval=good)
        d = self.decision(report)
        self.assertEqual((d["decision"], d["reason_code"]), (gv.ADMIT, gv.R_APPROVED))
        self.assertEqual(d["evidence_refs"]["approved_by"], "operator-synthetic")
        self.assertEqual(sum(r["status"] == co.PRODUCED for r in report["lens_runs"]), 7)
        self.assertEqual(self.decision(self.run_cycle([self.lead_claim], approval=good))["reason_code"], gv.R_DUPLICATE)

    def test_approvals_cannot_override_refusals_or_come_from_components(self):
        cycle = self.g.evaluate(self.request([self.lead_claim])).cycle_id
        for reason in (gv.R_DUPLICATE, gv.R_BUDGET, gv.R_NO_NEW_EVIDENCE, gv.R_ADMITTED):
            with self.subTest(reason), self.assertRaises(gv.GovernorError):
                self.g.record_approval(cycle, reason, "operator-synthetic")
        for approver in ("lens-muse", "coordinator", "synthetic-emitter-1"):
            with self.subTest(approver), self.assertRaises(gv.GovernorError):
                self.g.record_approval(cycle, gv.R_COMMERCIAL, approver)

    def test_a_lens_cannot_approve_its_own_cycle(self):
        governor = self.g

        def self_approve(brief):
            governor.record_approval("cxp-cycle-" + "1" * 64, gv.R_COMMERCIAL, "operator-synthetic")
        report = self.run_cycle([self.obs_a], lens_list=spies(CATALYST=self_approve))
        catalyst = next(r for r in report["lens_runs"] if r["lens_id"] == "CATALYST")
        self.assertEqual((catalyst["status"], catalyst["error"]), (co.FAILED, "GovernorError"))
        self.assertEqual([e for e in self.g.ledger_entries() if e["entry"] == "APPROVAL"], [])

    def test_recycled_root_cycles_need_a_human(self):
        self.run_cycle([self.obs_a])
        lens_rid = next(m["record_id"] for m in self.x.all_record_metadata()
                        if m["kind"] == cxp.KIND_LENS_OUTPUT and m["lens_id"] == "ARCHITECT")
        recycled = self.accept(ev.claim([lens_rid], statement="Architect output, restated as a claim."))
        d = self.g.evaluate(self.request([recycled]))
        self.assertEqual((d.decision, d.reason_code), (gv.NEEDS_HUMAN, gv.R_RECYCLED))
        approval = self.g.record_approval(d.cycle_id, gv.R_RECYCLED, "operator-synthetic")
        self.assertEqual(self.g.admit(self.request([recycled], approval=approval)).decision, gv.ADMIT)


class TestNoSelfAuthorization(GovernorTestCase):
    def test_governed_lens_outputs_stay_unverified_interpretations(self):
        report = self.run_cycle([self.obs_a])
        for r in report["assembly"]["lens_results"]:
            meta = self.x.record_metadata(r["record_id"])
            self.assertEqual((meta["provenance"], meta["verification"]), (cxp.UNVERIFIED_INTERPRETATION, cxp.VER_UNVERIFIED))
            self.assertNotEqual(meta["evidence"], cxp.EV_INDEPENDENT_SOURCES)
        self.assertFalse(report["grants_execution_authority"])
        self.assertFalse(self.decision(report)["grants_execution_authority"])

    def test_no_authority_bearing_surface(self):
        self.assertFalse(self.g.grants_execution_authority)
        self.assertFalse(policy().grants_execution_authority)
        for obj in (gv.RecursionGovernor, gv.CycleDecision, gv.GovernorPolicy):
            for name in dir(obj):
                for word in ("execute", "publish", "contact", "spend", "charge", "grant_", "authorize", "promote"):
                    self.assertNotIn(word, name.lower(), f"{obj.__name__}.{name}")

    def test_ungoverned_coordinator_refuses_cycle_arguments(self):
        c = co.LensCoordinator(self.x)
        with self.assertRaises(co.CoordinatorError):
            c.run([self.obs_a], TOPIC, T, parent_cycle_id="cxp-cycle-" + "0" * 64)


class TestDeterministicReplay(GovernorTestCase):
    def _sequence(self, x, g):
        def run(inputs, parent=None):
            return co.LensCoordinator(x, governor=g).run(inputs, TOPIC, T, parent_cycle_id=parent)["governor_decision"]
        a = x.ingest(synthetic.phase0_observation_event()).record_id
        b = x.ingest(ev.observation(statement="The phone node refused a self-signed grant.",
                                    sources=[ev.source("synthetic://bench-log-b", source_type="test_run")])).record_id
        root = run([a])
        return [root, run([a]), run([b], root["cycle_id"]), run([b], root["cycle_id"])]

    def test_same_requests_same_decisions_same_ledger(self):
        results = []
        for name in ("one", "two"):
            x = exchange.CognitiveExchange(self.tmp / f"replay-{name}" / "store")
            g = gv.RecursionGovernor(x, self.tmp / f"replay-{name}" / "governor", policy())
            results.append(self._sequence(x, g))
        self.assertEqual(results[0], results[1])
        self.assertEqual([d["reason_code"] for d in results[0]], [gv.R_ADMITTED, gv.R_DUPLICATE, gv.R_ADMITTED, gv.R_DUPLICATE])
        self.assertEqual(snapshot(self.tmp / "replay-one"), snapshot(self.tmp / "replay-two"))


if __name__ == "__main__":
    unittest.main()
