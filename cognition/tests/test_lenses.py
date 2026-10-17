"""R3 seven-lens and coordinator acceptance tests. Deterministic, local,
temporary stores only; the demonstration input is the real Phase 0 commit
subject (synthetic.phase0_observation_event)."""
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition.tests import _events as ev
from cognition.tests.test_exchange import snapshot
from cognition import contradiction, coordinator as co, cxp, exchange, lenses, lineage, synthetic

TOPIC = "Receiver-held authorization in ForgeWorld"
T1, T2 = "2026-10-17T01:00:00Z", "2026-10-18T01:00:00Z"


class Spy:
    """Wraps a lens, counting calls and remembering the brief object it got."""

    def __init__(self, inner, behaviour=None):
        self.inner, self.behaviour = inner, behaviour
        self.lens_id, self.lens_version, self.representation = inner.lens_id, inner.lens_version, inner.representation
        self.calls, self.briefs = 0, []

    def analyze(self, brief):
        self.calls += 1
        self.briefs.append(brief)
        return self.behaviour(brief) if self.behaviour else self.inner.analyze(brief)


def spies(**behaviours):
    return [Spy(lens, behaviours.get(lens.lens_id)) for lens in lenses.LENSES]


class LensTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-r3-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.x = exchange.CognitiveExchange(self.tmp / "store")
        self.obs = self.x.ingest(synthetic.phase0_observation_event()).record_id

    def run_lenses(self, lens_list=None, budget=co.LensBudget(), x=None, inputs=None, at=T1):
        c = co.LensCoordinator(x or self.x, lens_list or lenses.LENSES, budget)
        return c.run(inputs or [self.obs], TOPIC, at)

    def statuses(self, report):
        return {r["lens_id"]: r["status"] for r in report["lens_runs"]}


class TestRegistry(unittest.TestCase):
    def test_seven_registered_lenses(self):
        self.assertEqual(tuple(l.lens_id for l in lenses.LENSES), cxp.LENS_IDS)
        self.assertEqual(len(cxp.LENS_IDS), 7)
        for lens in lenses.LENSES:
            self.assertEqual(lens.lens_version, lenses.LENS_VERSION)
            self.assertIn(lens.representation, cxp.REPRESENTATIONS)
            self.assertNotEqual(lens.representation, cxp.REP_QUOTATION)

    def test_coordinator_refuses_bad_lens_sets(self):
        x = exchange.CognitiveExchange(Path(tempfile.mkdtemp(prefix="cxp-r3-reg-")))
        self.addCleanup(shutil.rmtree, x.root, ignore_errors=True)
        with self.assertRaises(ValueError):
            co.LensCoordinator(x, [lenses.Muse(), lenses.Muse()])

        class Unknown(lenses.Muse):
            lens_id = "ORACLE"

        class Quoter(lenses.Muse):
            representation = cxp.REP_QUOTATION

        for bad in (Unknown(), Quoter()):
            with self.assertRaises(ValueError):
                co.LensCoordinator(x, [bad])
        for bad in (dict(max_inputs=0), dict(max_lens_invocations=8), dict(max_inputs=True)):
            with self.assertRaises(ValueError):
                co.LensBudget(**bad)


class TestDemonstration(LensTestCase):
    def test_observation_to_seven_lenses_to_assembled_brief(self):
        report = self.run_lenses()
        self.assertEqual(set(self.statuses(report).values()), {co.PRODUCED})
        a = report["assembly"]
        self.assertTrue(a["complete"])
        self.assertEqual([r["lens_id"] for r in a["lens_results"]], list(cxp.LENS_IDS))
        self.assertEqual(a["inputs"][0]["statement"], synthetic.PHASE0_SUBJECT)
        self.assertEqual(a["source_lineage"][0]["sources"][0]["locator"], synthetic.PHASE0_COMMIT)
        self.assertEqual(a["episode_planning_seed"]["working_title"], "We Built an AI That Cannot Give Itself Permission")
        self.assertEqual(a["episode_planning_seed"]["representation"], cxp.REP_DRAMATIZATION)
        self.assertEqual(a["status"], "CANDIDATE_REQUIRES_HUMAN_REVIEW")
        self.assertEqual({d["question"] for d in a["disagreements"]},
                         {cxp.Q_CLAIM_ESTABLISHED, cxp.Q_READY_FOR_EPISODE})
        self.assertEqual([u["question"] for u in a["unopposed_positions"]], [cxp.Q_NEEDS_EXPERIMENT])
        self.assertEqual(len(a["candidate_next_actions"]), 7)


class TestSharedImmutableInput(LensTestCase):
    def test_every_lens_gets_the_same_frozen_brief(self):
        ls = spies()
        self.run_lenses(ls)
        briefs = [s.briefs[0] for s in ls]
        self.assertTrue(all(b is briefs[0] for b in briefs))
        brief = briefs[0]
        with self.assertRaises(TypeError):
            brief.inputs[0]["statement"] = "tampered"
        with self.assertRaises(TypeError):
            brief.facts["all_verified"] = True
        with self.assertRaises(AttributeError):
            brief.inputs.append({})

    def test_a_lens_that_tries_to_mutate_the_brief_is_isolated(self):
        def vandal(brief):
            brief.facts["all_verified"] = True
        ls = spies(MUSE=vandal)
        report = self.run_lenses(ls)
        self.assertEqual(report["lens_runs"][0]["status"], co.FAILED)
        self.assertEqual(report["lens_runs"][0]["error"], "TypeError")
        scientist = next(r for r in report["assembly"]["lens_results"] if r["lens_id"] == "SCIENTIST")
        self.assertEqual(scientist["positions"][cxp.Q_CLAIM_ESTABLISHED], cxp.POS_OPPOSE)  # still saw unverified


class TestOutputIdentityAndProvenance(LensTestCase):
    def test_distinct_identities_and_preserved_lineage(self):
        results = self.run_lenses()["assembly"]["lens_results"]
        record_ids = {r["record_id"] for r in results}
        self.assertEqual(len(record_ids), 7)
        self.assertEqual(len({self.x.get_record(rid).content_id for rid in record_ids}), 7)
        for r in results:
            meta = self.x.record_metadata(r["record_id"])
            self.assertEqual(meta["kind"], cxp.KIND_LENS_OUTPUT)
            self.assertEqual(meta["derived_from"], [self.obs])
            self.assertEqual(r["input_record_ids"], [self.obs])
            self.assertEqual(r["provenance"], cxp.UNVERIFIED_INTERPRETATION)
            self.assertEqual(r["lineage"]["observation_roots"], [self.obs])
            self.assertEqual(r["lineage"]["epistemic_class"], lineage.INFERRED)
            trace = lineage.trace(self.x.record_metadata, r["record_id"])
            self.assertEqual(trace["sources"][0]["locator"], synthetic.PHASE0_COMMIT)


class TestNoInflation(LensTestCase):
    def test_lens_evidence_never_exceeds_input_and_generated_content_has_none(self):
        for r in self.run_lenses()["assembly"]["lens_results"]:
            expected = cxp.EV_NONE if r["representation"] in (cxp.REP_HYPOTHESIS, cxp.REP_DRAMATIZATION) else cxp.EV_SINGLE_SOURCE
            self.assertEqual(r["evidence"], expected, r["lens_id"])
            self.assertEqual(r["verification"], cxp.VER_UNVERIFIED)

    def test_weak_input_gives_weak_lens_output(self):
        weak = self.x.ingest(ev.observation(statement="Grants are held by the receiver.", evidence=cxp.EV_NONE)).record_id
        report = self.run_lenses(inputs=[weak])
        self.assertEqual({r["evidence"] for r in report["assembly"]["lens_results"]}, {cxp.EV_NONE})

    def test_hand_built_lens_outputs_cannot_inflate(self):
        def lens_event(**overrides):
            event = {"schema_version": 1, "kind": cxp.KIND_LENS_OUTPUT, "representation": cxp.REP_INFERENCE,
                     "evidence": cxp.EV_SINGLE_SOURCE, "verification": cxp.VER_UNVERIFIED,
                     "provenance": cxp.UNVERIFIED_INTERPRETATION, "privacy": cxp.PRIV_INTERNAL,
                     "payload": {"lens_id": "MUSE", "lens_version": "9", "statement": "s", "positions": {},
                                 "uncertainties": [], "unsupported_claims": [], "next_action": None, "details": {}},
                     "sources": [], "derived_from": [self.obs], "verification_ref": None, "consent_ref": None,
                     "occurrence": {"emitter_id": "rogue", "observed_at": T1}}
            event.update(overrides)
            return event
        cases = {
            "evidence": (lens_event(evidence=cxp.EV_INDEPENDENT_SOURCES), cxp.E_EVIDENCE_INFLATION),
            "verified": (lens_event(verification=cxp.VER_VERIFIED, verification_ref="cxp-rec-" + "0" * 64), cxp.E_KIND_RULE),
            "observed": (lens_event(provenance=cxp.OBSERVED), cxp.E_KIND_RULE),
            "quotation": (lens_event(representation=cxp.REP_QUOTATION), cxp.E_KIND_RULE),
            "privacy": (lens_event(privacy=cxp.PRIV_PUBLIC), cxp.E_PRIVACY_DOWNGRADE),
        }
        for name, (event, code) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.x.ingest(event).error_code, code)

    def test_lens_cannot_set_its_own_labels_or_authority(self):
        def labels(brief):
            out = lenses.Muse().analyze(brief)
            out["verification"] = cxp.VER_VERIFIED
            return out

        def authority(brief):
            out = lenses.Scientist().analyze(brief)
            out["details"] = {"grant": "content_read"}
            return out

        def bad_position(brief):
            out = lenses.Architect().analyze(brief)
            out["positions"] = {cxp.Q_CLAIM_ESTABLISHED: "PROVEN"}
            return out
        report = self.run_lenses(spies(MUSE=labels, SCIENTIST=authority, ARCHITECT=bad_position))
        runs = {r["lens_id"]: (r["status"], r["error"]) for r in report["lens_runs"]}
        self.assertEqual(runs["MUSE"], (co.REJECTED, cxp.E_MALFORMED))
        self.assertEqual(runs["SCIENTIST"], (co.REJECTED, cxp.E_AUTHORITY_FIELD_FORBIDDEN))
        self.assertEqual(runs["ARCHITECT"], (co.REJECTED, cxp.E_MALFORMED))
        self.assertEqual(runs["CATALYST"][0], co.PRODUCED)

    def test_verified_input_still_yields_unverified_interpretations(self):
        vr = self.x.ingest(ev.verification_result(self.x.get_record(self.obs).content_id)).record_id
        verified = self.x.ingest(dict(synthetic.phase0_observation_event(), verification=cxp.VER_VERIFIED,
                                      verification_ref=vr)).record_id
        a = self.run_lenses(inputs=[verified])["assembly"]
        self.assertEqual(a["epistemic_status"]["input_verification"], cxp.VER_VERIFIED)
        self.assertEqual({r["verification"] for r in a["lens_results"]}, {cxp.VER_UNVERIFIED})
        self.assertFalse(a["epistemic_status"]["lens_outputs_are_evidence"])


class TestContradictionPreservation(LensTestCase):
    def test_disagreements_become_open_contradictions_with_every_position_kept(self):
        a = self.run_lenses()["assembly"]
        by_q = {d["question"]: d for d in a["disagreements"]}
        established = by_q[cxp.Q_CLAIM_ESTABLISHED]
        self.assertEqual(established["positions"], {cxp.POS_SUPPORT: ["ARCHITECT"],
                                                    cxp.POS_OPPOSE: ["CHALLENGER", "SCIENTIST"], cxp.POS_UNCERTAIN: []})
        ready = by_q[cxp.Q_READY_FOR_EPISODE]
        self.assertEqual(ready["positions"], {cxp.POS_SUPPORT: ["MUSE", "STORYWEAVER"],
                                              cxp.POS_OPPOSE: ["CHALLENGER"], cxp.POS_UNCERTAIN: ["EMPATH"]})
        lens_record = {r["lens_id"]: r["record_id"] for r in a["lens_results"]}
        for d, members in ((established, ["ARCHITECT", "CHALLENGER", "SCIENTIST"]),
                           (ready, ["CHALLENGER", "MUSE", "STORYWEAVER"])):
            self.assertEqual(d["contradiction_status"], contradiction.OPEN)  # a 2-to-1 majority resolves nothing
            meta = self.x.record_metadata(d["contradiction_id"])
            self.assertEqual(meta["contradiction_claims"], sorted(lens_record[m] for m in members))

    def test_no_consensus_is_manufactured(self):
        a = self.run_lenses()["assembly"]
        self.assertNotIn("consensus", a)
        unopposed = a["unopposed_positions"][0]
        self.assertIn("not consensus", unopposed["note"])
        self.assertEqual(unopposed["lenses"], ["CATALYST", "SCIENTIST"])

    def test_lens_outputs_are_never_lens_input(self):
        a = self.run_lenses()["assembly"]
        lens_rid = a["lens_results"][0]["record_id"]
        with self.assertRaises(co.CoordinatorError) as ctx:
            self.run_lenses(inputs=[lens_rid])
        self.assertEqual(ctx.exception.code, co.E_INPUT_KIND)
        with self.assertRaises(co.CoordinatorError):
            self.run_lenses(inputs=[a["disagreements"][0]["contradiction_id"]])
        smuggled = {"schema_version": 1, "kind": cxp.KIND_LENS_OUTPUT, "representation": cxp.REP_INFERENCE,
                    "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
                    "provenance": cxp.UNVERIFIED_INTERPRETATION, "privacy": cxp.PRIV_INTERNAL,
                    "payload": {"lens_id": "MUSE", "lens_version": "2", "statement": "meta", "positions": {},
                                "uncertainties": [], "unsupported_claims": [], "next_action": None, "details": {}},
                    "sources": [], "derived_from": [lens_rid], "verification_ref": None, "consent_ref": None,
                    "occurrence": {"emitter_id": "rogue", "observed_at": T1}}
        self.assertEqual(self.x.ingest(smuggled).error_code, cxp.E_KIND_RULE)


class TestFailureIsolationAndDuplicates(LensTestCase):
    def test_failed_lens_is_isolated_and_retried_alone(self):
        def broken(brief):
            raise RuntimeError("synthetic lens failure")
        report = self.run_lenses(spies(EMPATH=broken))
        self.assertEqual(self.statuses(report)["EMPATH"], co.FAILED)
        self.assertEqual(sum(s == co.PRODUCED for s in self.statuses(report).values()), 6)
        self.assertFalse(report["assembly"]["complete"])
        ls = spies()
        retry = self.run_lenses(ls)
        self.assertEqual(self.statuses(retry)["EMPATH"], co.PRODUCED)
        self.assertEqual({s.lens_id: s.calls for s in ls if s.calls}, {"EMPATH": 1})
        self.assertTrue(retry["assembly"]["complete"])

    def test_rerun_invokes_nothing_and_writes_nothing(self):
        self.run_lenses()
        before = snapshot(self.tmp / "store")
        ls = spies()
        again = self.run_lenses(ls, at=T2)
        self.assertEqual(set(self.statuses(again).values()), {co.ALREADY_PROCESSED})
        self.assertEqual((sum(s.calls for s in ls), again["invocations_used"], again["contradictions_created"]), (0, 0, 0))
        self.assertEqual(snapshot(self.tmp / "store"), before)


class TestDeterminismAndBounds(LensTestCase):
    def test_assembly_is_deterministic(self):
        first = self.run_lenses()["assembly"]
        other = exchange.CognitiveExchange(self.tmp / "other")
        obs = other.ingest(synthetic.phase0_observation_event()).record_id
        self.assertEqual(obs, self.obs)
        self.assertEqual(self.run_lenses(x=other)["assembly"], first)
        self.assertEqual(self.run_lenses(at=T2)["assembly"], first)
        self.assertTrue(first["assembly_id"].startswith("cxp-asm-"))

    def test_invocation_budget_is_enforced(self):
        ls = spies()
        report = self.run_lenses(ls, budget=co.LensBudget(max_lens_invocations=3))
        self.assertEqual(sum(s.calls for s in ls), 3)
        self.assertEqual(list(self.statuses(report).values()).count(co.BUDGET_EXHAUSTED), 4)
        self.assertFalse(report["assembly"]["complete"])
        self.assertLessEqual(report["contradictions_created"], len(cxp.LENS_QUESTIONS))

    def test_input_budget_is_enforced(self):
        ids = [self.x.ingest(ev.observation(statement=f"note {i}")).record_id for i in range(3)]
        with self.assertRaises(co.CoordinatorError) as ctx:
            self.run_lenses(inputs=ids, budget=co.LensBudget(max_inputs=2))
        self.assertEqual(ctx.exception.code, co.E_BUDGET)

    def test_coordinator_refuses_to_invoke_itself(self):
        holder = {}

        def recursive(brief):
            return holder["c"].run([self_obs], TOPIC, T2)
        self_obs = self.obs
        c = co.LensCoordinator(self.x, spies(CATALYST=recursive))
        holder["c"] = c
        report = c.run([self.obs], TOPIC, T1)
        self.assertEqual(self.statuses(report)["CATALYST"], co.FAILED)
        self.assertEqual(report["lens_runs"][-1]["error"], "CoordinatorError")
        self.assertEqual(sum(s == co.PRODUCED for s in self.statuses(report).values()), 6)


class TestAuthorityAndErasure(LensTestCase):
    def test_no_execution_authority_anywhere(self):
        c = co.LensCoordinator(self.x)
        report = c.run([self.obs], TOPIC, T1)
        self.assertFalse(c.grants_execution_authority)
        self.assertFalse(report["grants_execution_authority"])
        self.assertFalse(report["assembly"]["grants_execution_authority"])
        for rid in (r["record_id"] for r in report["lens_runs"]):
            self.assertFalse(self.x.get_record(rid).grants_execution_authority)
        for obj in (co.LensCoordinator, *[type(l) for l in lenses.LENSES]):
            for name in dir(obj):
                for word in ("execute", "authorize", "grant_", "issue", "permit"):
                    self.assertNotIn(word, name.lower(), f"{obj.__name__}.{name}")
        self.assertEqual({p.relative_to(self.tmp).parts[0] for p in self.tmp.rglob("*")}, {"store"})

    def test_erased_input_stops_the_run_before_any_lens(self):
        self.x.erase(self.obs, "synthetic-erasure")
        ls = spies()
        with self.assertRaises(co.CoordinatorError) as ctx:
            self.run_lenses(ls)
        self.assertEqual(ctx.exception.code, cxp.E_ERASED)
        self.assertEqual(sum(s.calls for s in ls), 0)

    def test_erased_lens_output_is_not_reproduced(self):
        first = self.run_lenses()
        muse = first["lens_runs"][0]["record_id"]
        ready = next(d for d in first["assembly"]["disagreements"] if d["question"] == cxp.Q_READY_FOR_EPISODE)
        self.x.erase(muse, "synthetic-erasure")
        ls = spies()
        again = self.run_lenses(ls, at=T2)
        self.assertEqual(self.statuses(again)["MUSE"], co.ERASED)
        self.assertEqual(sum(s.calls for s in ls), 0)
        muse_result = again["assembly"]["lens_results"][0]
        self.assertFalse(muse_result["available"])
        self.assertNotIn("statement", muse_result)
        self.assertFalse(again["assembly"]["complete"])
        self.assertEqual(contradiction.assess(self.x, ready["contradiction_id"])["status"], contradiction.VOID)
        new_ready = next(d for d in again["assembly"]["disagreements"] if d["question"] == cxp.Q_READY_FOR_EPISODE)
        self.assertEqual(new_ready["positions"][cxp.POS_SUPPORT], ["STORYWEAVER"])
        self.assertNotEqual(new_ready["contradiction_id"], ready["contradiction_id"])


if __name__ == "__main__":
    unittest.main()
