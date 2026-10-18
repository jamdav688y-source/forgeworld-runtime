"""ODCC-1: ORIGIN brief, OUTCOME_SPEC and the spec-bound delivery lifecycle.
Synthetic fixtures; temporary stores; no network, probe, payment, contact or
platform access. Numbered comments map to the mission's required tests."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cognition import bundle, commerce as cm, cxp, cycle, delivery as dv, destination as ds, episode as ep
from cognition import exchange, governor as gv, origin
from cognition.tests import _events as ev
from cognition.tests._commerce_events import signal
from cognition.tests.test_episode import EpisodeTestCase
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_lenses import spies

REPO = Path(__file__).resolve().parents[2]
CUSTOMER, PROJECT = "customer-synthetic-northwind-repairs", "project-synthetic-intake-diagnostic"
OFFER, ENG, ACCT = "offer-workflow-loss-diagnostic", "eng-synthetic-northwind", "acct-synthetic-northwind"
TOPIC = "Northwind (synthetic): requests lost between first contact and staff assignment"
TAGS = ["analysis", "data_processing", "documentation", "process_mining"]
T = [f"2026-10-19T{h:02d}:00:00Z" for h in range(6, 20)]
EDITOR, REVIEWER, SIGNER, COURIER, AUTHOR = ("operator-analyst", "operator-qa-lead", "operator-account-lead",
                                             "operator-courier", "operator-engagement-lead")
CRITERIA = [
    {"criterion_id": "ac-map-present", "check": "artifact_present", "path": "workflow_map.md",
     "description": "A current-state workflow map is included"},
    {"criterion_id": "ac-uncertainty-register", "check": "contains_text", "path": "report.md",
     "text": "## Evidence and uncertainty register", "description": "Every finding carries its evidence status"},
    {"criterion_id": "ac-validation-plan", "check": "contains_text", "path": "report.md",
     "text": "## Validation plan", "description": "The automation proposal has a validation plan"},
    {"criterion_id": "ac-findings-table", "check": "artifact_present", "path": "findings.csv",
     "description": "Prioritized findings are included"},
    {"criterion_id": "ac-reviewer-checks-claims", "check": "human_judgement",
     "description": "A reviewer confirms no finding is stated more strongly than its evidence"},
]
DISCLOSURES = ["Synthetic engagement: no real customer data.", "Delay durations are unmeasured."]
DELIVERABLES = ["findings.csv", "report.md", "workflow_map.md"]


def observation(text, locator, key=None):
    return ev.observation(statement=text, sources=[ev.source(f"customer:{CUSTOMER}/{locator}", independence_key=key)])


CALL = observation("Customer on the intake call: 'phone requests are sometimes never assigned to anyone.'",
                   "intake/call-001")
EXPORT = observation("Synthetic ticket export: 14 of 120 web-form requests have no assignee after 48 hours.",
                     "export/tickets-2026-09", key="northwind-ticketing-system")


def solution(with_plan=True):
    report = ("# Workflow-loss diagnostic (SYNTHETIC)\n\n## Findings\n1. Phone requests have no owner before the "
              "weekly meeting.\n\n## Evidence and uncertainty register\n- Finding 1: customer assertion, unverified.\n")
    if with_plan:
        report += "\n## Validation plan\nMeasure owner-within-one-hour for four weeks.\n"
    return {"workflow_map.md": b"# Current state (SYNTHETIC)\nphone/web -> inbox -> [no owner] -> weekly meeting\n",
            "report.md": report.encode(), "findings.csv": b"rank,finding,evidence_status\n1,no owner,customer_assertion\n"}


def raw(kind, payload, derived_from, emitter=AUTHOR, at=T[0], **labels):
    event = {"schema_version": 1, "kind": kind, "representation": cxp.REP_PARAPHRASE, "evidence": cxp.EV_NONE,
             "verification": cxp.VER_UNVERIFIED, "provenance": cxp.HUMAN_ASSERTED, "privacy": cxp.PRIV_INTERNAL,
             "payload": payload, "sources": [], "derived_from": sorted(derived_from), "verification_ref": None,
             "consent_ref": None, "occurrence": {"emitter_id": emitter, "observed_at": at}}
    event.update(labels)
    return event


class ODCCTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-odcc-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.registry = origin.load_capability_registry(REPO / "capabilities" / "registry.json")
        self.boot(self.tmp / "a")
        self.estimate = self.accept(signal(cm.ESTIMATE_RECORDED, engagement=ENG, account=ACCT,
                                           representation=cxp.REP_HYPOTHESIS, offer_ref=OFFER,
                                           amount={"minor": 500000, "currency": "USD"}, reason="PRICE_HYPOTHESIS"))
        self.cycle = self.runner.run([CALL, EXPORT], TOPIC, T[0])
        self.brief = self.make_brief()

    def boot(self, root):
        self.root = root
        self.x, self.g, self.runner, self.intake, self.studio = EpisodeTestCase.make(root)
        self.desk = dv.DeliveryDesk(self.x, self.g, root / "deliveries")
        self.outcomes = ds.OutcomeDesk(self.x, self.runner, self.desk)

    def accept(self, event):
        receipt = self.x.ingest(event)
        self.assertEqual(receipt.status, exchange.ACCEPTED, (receipt.error_code, receipt.detail))
        return receipt.record_id

    def make_brief(self, artifact_id=None, **kw):
        kw.setdefault("value_hypothesis_ids", [self.estimate])
        kw.setdefault("missing_information", ["Measured delay per stage"])
        return origin.origin_brief(self.x, self.runner, artifact_id or self.cycle["artifact_id"],
                                   capability_registry=self.registry, required_tags=TAGS, **kw)

    def propose(self, brief=None, **overrides):
        kw = dict(project_ref=PROJECT, customer_ref=CUSTOMER, synthetic=True,
                  intended_outcome="Show where requests disappear, with one bounded automation proposal.",
                  acceptance_criteria=copy.deepcopy(CRITERIA), required_deliverables=list(DELIVERABLES),
                  disclosures=list(DISCLOSURES), author_id=AUTHOR, observed_at=T[1])
        kw.update(overrides)
        return self.outcomes.propose(brief or self.brief, **kw)

    def assemble(self, spec_id, artifacts=None, **overrides):
        kw = dict(project_ref=PROJECT, customer_ref=CUSTOMER, synthetic=True, editor_id=EDITOR,
                  artifacts=artifacts or solution(), source_artifact_ids=[r["record_id"] for r in self.brief["initiating_records"]],
                  acceptance_criteria=copy.deepcopy(CRITERIA), known_limitations=list(DISCLOSURES), created_at=T[2],
                  outcome_spec_id=spec_id)
        kw.update(overrides)
        return self.desk.assemble(**kw)

    def through_delivery(self, package_id):
        self.desk.review(package_id, REVIEWER, ep.APPROVED, T[3], criteria_judged=["ac-reviewer-checks-claims"])
        self.desk.sign_handoff(package_id, SIGNER, T[4])
        self.desk.record_delivery(package_id, COURIER, dv.CHANNEL_SYNTHETIC, T[5])

    def customer_outcome(self, package_id, event, words):
        evidence = self.accept(ev.observation(statement=words,
                                              sources=[ev.source(f"customer:{CUSTOMER}/{package_id}/reply-001")]))
        self.desk.record_customer_outcome(package_id, COURIER, event, evidence, "sha256:" + bundle.sha256_hex(words.encode()), T[6])
        return evidence

    def package_event(self, spec, package, **changes):
        """A raw DELIVERY_PACKAGE event cloned from a desk-built one, for ingest-level refusal tests."""
        payload = {**self.x.get_record(package["package_record_id"]).payload(), **changes}
        payload["package_id"] = "cxp-dlv-" + "3" * 64
        return raw(cxp.KIND_DELIVERY_PACKAGE, payload, set(payload["source_artifact_ids"]), emitter=EDITOR)

    def refused(self, fn, expected, exc=Exception):
        before = snapshot(self.root)
        with self.assertRaises(exc) as ctx:
            fn()
        reasons = getattr(ctx.exception, "reasons", [str(ctx.exception)])
        self.assertTrue(any(expected in r for r in reasons), reasons)
        self.assertEqual(snapshot(self.root), before)


class TestOrigin(ODCCTestCase):
    def test_01_completed_governed_cycle_produces_brief(self):
        b = self.brief
        self.assertEqual((b["governance"]["decision"], b["governance"]["termination"]),
                         (gv.ADMIT, cycle.COMPLETED_WITH_CANDIDATES))
        self.assertEqual([r["epistemic_class"] for r in b["initiating_records"]], ["DIRECT_OBSERVATION"] * 2)
        self.assertEqual(b["independence"]["independent_origin_count"], 2)
        self.assertEqual(b["derived_inputs"], [])
        matches = {m["capability_id"]: m for m in b["capabilities"]["matches"]}
        self.assertEqual((matches["python"]["matched_count"], matches["python"]["required_count"]), (2, 4))
        self.assertTrue(all(m["reachability"] == origin.NOT_PROBED and m["authorized"] is False for m in matches.values()))
        self.assertEqual(b["capabilities"]["uncovered_tags"], ["process_mining"])
        self.assertEqual(b["uncertainty"]["missing_information"], ["Measured delay per stage"])
        self.assertTrue(b["uncertainty"]["methodology_notes"])  # separated, not presented as open questions
        self.assertEqual(b["smallest_next_step"][0]["evidence_status"], "NOT_EVIDENCE")
        cxp.canonical_bytes(b)  # no floats anywhere: CXP canonicalization accepts it
        self.assertEqual(self.make_brief(), b)  # deterministic

    def test_02_incomplete_or_unadmitted_cycles_are_refused(self):
        again = self.runner.run([], TOPIC, T[3], extra_input_ids=[r["record_id"] for r in self.brief["initiating_records"]])
        self.assertNotIn(again["termination"], origin.COMPLETED)
        self.refused(lambda: self.make_brief(again["artifact_id"]), origin.O_NOT_COMPLETED, origin.OriginRefused)
        rejected = self.runner.run([ev.claim([self.estimate])], TOPIC, T[3])
        self.refused(lambda: self.make_brief(rejected["artifact_id"]), cycle.SOURCE_REJECTED, origin.OriginRefused)
        self.refused(lambda: self.make_brief("cxp-art-" + "0" * 64), origin.O_UNKNOWN_ARTIFACT, origin.OriginRefused)

        def broken(brief):
            raise RuntimeError("synthetic lens failure")
        partial_x, _, partial_runner, _, _ = EpisodeTestCase.make(self.tmp / "partial", lenses=spies(MUSE=broken))
        partial = partial_runner.run([CALL], TOPIC, T[0])
        self.assertEqual(partial["termination"], cycle.COMPLETED_PARTIAL)
        with self.assertRaises(origin.OriginRefused):
            origin.origin_brief(partial_x, partial_runner, partial["artifact_id"], capability_registry=self.registry,
                                required_tags=TAGS)
        path = self.root / "artifacts" / f"{self.cycle['artifact_id']}.json"
        data = json.loads(path.read_text())
        data["governor_decision"]["decision"] = gv.ADMIT
        data["termination"] = cycle.COMPLETED_WITH_CANDIDATES
        data["topic"] = "edited"
        path.write_text(json.dumps(data))
        self.refused(lambda: self.make_brief(), origin.O_UNKNOWN_ARTIFACT, origin.OriginRefused)

    def test_02b_forged_consistent_artifact_without_admission_is_refused(self):
        """Defence in depth: a content-consistent artifact claiming completion without an R4 ADMIT."""
        artifact = copy.deepcopy(self.cycle)
        artifact["governor_decision"]["decision"] = gv.NEEDS_HUMAN
        content = {k: v for k, v in artifact.items() if k != "artifact_id"}
        artifact["artifact_id"] = cxp.digest_id("cycle_artifact", content)
        (self.root / "artifacts" / f"{artifact['artifact_id']}.json").write_text(json.dumps(artifact))
        self.refused(lambda: self.make_brief(artifact["artifact_id"]), origin.O_NOT_ADMITTED, origin.OriginRefused)
        artifact = copy.deepcopy(self.cycle)
        artifact["governor_decision"]["committed"] = False
        content = {k: v for k, v in artifact.items() if k != "artifact_id"}
        artifact["artifact_id"] = cxp.digest_id("cycle_artifact", content)
        (self.root / "artifacts" / f"{artifact['artifact_id']}.json").write_text(json.dumps(artifact))
        self.refused(lambda: self.make_brief(artifact["artifact_id"]), origin.O_NOT_ADMITTED, origin.OriginRefused)

    def test_03_independent_lineage_is_preserved(self):
        same_words = "Requests go missing between intake and assignment."
        twins = self.runner.run([observation(same_words, "intake/call-101"), observation(same_words, "intake/call-102")],
                                TOPIC + " twins", T[3])
        b = self.make_brief(twins["artifact_id"])
        self.assertEqual((len(b["initiating_records"]), b["independence"]["independent_origin_count"]), (2, 2))
        shared = self.runner.run([observation("Export row 1 lacks an owner.", "export/a", key="one-system"),
                                  observation("Export row 2 lacks an owner.", "export/b", key="one-system")],
                                 TOPIC + " shared", T[4])
        b = self.make_brief(shared["artifact_id"])
        self.assertEqual((len(b["initiating_records"]), b["independence"]["independent_origin_count"]), (2, 1))
        self.assertEqual(b["independence"]["repeated_origins"], ["one-system"])

    def test_04_inference_cannot_become_initiating_observation(self):
        call_id = self.brief["initiating_records"][0]["record_id"]
        claim = self.accept(ev.claim([call_id], statement="So the dispatcher is the bottleneck."))
        mixed = self.runner.run([observation("A new phone log.", "intake/call-201")], TOPIC + " mixed", T[3],
                                extra_input_ids=[claim])
        self.assertIn(mixed["termination"], origin.COMPLETED)
        b = self.make_brief(mixed["artifact_id"])
        self.assertNotIn(claim, [r["record_id"] for r in b["initiating_records"]])
        self.assertEqual([(d["record_id"], d["role"]) for d in b["derived_inputs"]],
                         [(claim, "DERIVED_INPUT_NOT_AN_INITIATING_OBSERVATION")])
        self.assertEqual(b["independence"]["independent_origin_count"], 1)  # the claim adds no corroboration
        altered = copy.deepcopy(self.brief)
        altered["initiating_records"].append({"record_id": claim})
        self.refused(lambda: self.propose(altered), "STALE_OR_ALTERED_ORIGIN_BRIEF", ds.DestinationRefused)
        spec = self.propose()["spec"]
        forged = {**spec, "initiating_record_ids": sorted(spec["initiating_record_ids"] + [claim])}
        forged["spec_id"] = ds.spec_id_of(forged)
        receipt = self.x.ingest(raw(cxp.KIND_OUTCOME_SPEC, forged, set(forged["initiating_record_ids"]) | {self.estimate}))
        self.assertEqual(receipt.error_code, cxp.E_TRANSITION_REFUSED)
        self.assertIn("inference cannot start an outcome", receipt.detail)

    def test_05_origin_never_probes(self):
        guarded = snapshot(REPO / "router") | snapshot(REPO / "capabilities")
        boom = mock.Mock(side_effect=AssertionError("network or process probe attempted"))
        with mock.patch("socket.socket", boom), mock.patch("socket.create_connection", boom), \
                mock.patch("subprocess.run", boom), mock.patch("subprocess.Popen", boom):
            self.make_brief()
        self.assertEqual(snapshot(REPO / "router") | snapshot(REPO / "capabilities"), guarded)
        source = Path(origin.__file__).read_text()
        for forbidden in ("import router", "mission_router", "import discover", "probe_all(", "route("):
            self.assertNotIn(forbidden, source.split('"""', 2)[2])

    def test_06_economic_hypotheses_remain_estimates(self):
        self.assertEqual([h["status"] for h in self.brief["value_hypotheses"]], ["HYPOTHESIS_NOT_REVENUE"])
        lead = self.accept(signal(cm.OPPORTUNITY_IDENTIFIED, engagement=ENG, account=ACCT, summary="Synthetic lead"))
        self.refused(lambda: self.make_brief(value_hypothesis_ids=[lead]), origin.O_BAD_HYPOTHESIS, origin.OriginRefused)
        spec = self.propose()["spec"]
        forged = {**spec, "value_hypothesis_ids": [lead]}
        forged["spec_id"] = ds.spec_id_of(forged)
        receipt = self.x.ingest(raw(cxp.KIND_OUTCOME_SPEC, forged, set(forged["initiating_record_ids"]) | {lead}))
        self.assertEqual(receipt.error_code, cxp.E_TRANSITION_REFUSED)


class TestOutcomeSpec(ODCCTestCase):
    def test_07_valid_spec_is_accepted(self):
        out = self.propose()
        spec, record = out["spec"], self.x.get_record(out["spec_record_id"])
        self.assertEqual((record.kind, record.provenance, record.evidence, record.verification),
                         (cxp.KIND_OUTCOME_SPEC, cxp.HUMAN_ASSERTED, cxp.EV_NONE, cxp.VER_UNVERIFIED))
        self.assertEqual(spec["spec_id"], ds.spec_id_of(spec))
        self.assertTrue(spec["spec_id"].startswith("cxp-osp-"))
        self.assertEqual(spec["criteria_sha256"], dv.criteria_sha256(CRITERIA))
        self.assertEqual(sorted(record.derived_from),
                         sorted([r["record_id"] for r in self.brief["initiating_records"]] + [self.estimate]))
        self.assertEqual([d["media_type"] for d in spec["required_deliverables"]],
                         ["text/csv", "text/markdown", "text/markdown"])
        self.assertEqual((spec["origin_cycle_artifact_id"], spec["origin_cycle_id"]),
                         (self.cycle["artifact_id"], self.cycle["governor_decision"]["cycle_id"]))
        self.assertEqual(self.propose()["spec_id"], spec["spec_id"])  # idempotent, deterministic

    def test_spec_payload_rules(self):
        cases = {
            "ACCEPTANCE_CRITERIA_REQUIRED": dict(acceptance_criteria=[]),
            "must disclose that it is synthetic": dict(disclosures=["Delay durations are unmeasured."]),
            "not a required deliverable": dict(required_deliverables=["report.md", "findings.csv"]),
            "UNAUTHORIZED_AUTHOR": dict(author_id="destination-bot"),
            "contact or banking": dict(intended_outcome="Email results to owner@example.com"),
        }
        for expected, override in cases.items():
            with self.subTest(expected):
                self.refused(lambda: self.propose(**override), expected, ds.DestinationRefused)
        spec = self.propose()["spec"]
        bad_hash = {**spec, "criteria_sha256": "0" * 64}
        bad_hash["spec_id"] = ds.spec_id_of(bad_hash)
        self.assertEqual(self.x.ingest(raw(cxp.KIND_OUTCOME_SPEC, bad_hash,
                                           set(spec["initiating_record_ids"]) | {self.estimate})).error_code,
                         cxp.E_MALFORMED)
        relabelled = raw(cxp.KIND_OUTCOME_SPEC, spec, set(spec["initiating_record_ids"]) | {self.estimate},
                         provenance=cxp.UNVERIFIED_INTERPRETATION)  # a model cannot author the contract
        receipt = self.x.ingest(relabelled)
        self.assertEqual(receipt.error_code, cxp.E_KIND_RULE)
        self.assertIn("human commitment", receipt.detail)
        with self.g.running():
            self.refused(lambda: self.propose(), "AUTHOR_DURING_RUNNING_CYCLE", ds.DestinationRefused)

    def test_08_changed_acceptance_criteria_are_refused(self):
        spec = self.propose()
        softer = copy.deepcopy(CRITERIA)[:-2]  # drop the validation-plan criterion... and the human check
        softer.append(CRITERIA[-1])
        self.refused(lambda: self.assemble(spec["spec_id"], acceptance_criteria=softer),
                     "CRITERIA_DIFFER_FROM_OUTCOME_SPEC", dv.DeliveryRefused)
        good = self.assemble(spec["spec_id"])
        receipt = self.x.ingest(self.package_event(spec, good, criteria_sha256=dv.criteria_sha256(softer)))
        self.assertEqual(receipt.error_code, cxp.E_TRANSITION_REFUSED)
        self.assertIn("acceptance criteria differ", receipt.detail)
        path = Path(good["directory"]) / dv.DELIVERY_FILE  # rewriting the bundle's criteria is caught on verify
        body = json.loads(path.read_bytes())
        body["acceptance_criteria"] = softer
        path.chmod(0o600)
        path.write_bytes(cxp.canonical_bytes(body))
        self.assertFalse(self.desk.verify(good["package_id"])["intact"])

    def test_09_missing_mandatory_spec_is_refused(self):
        real = dict(project_ref="project-intake-diagnostic", customer_ref="customer-northwind-repairs", synthetic=False)
        self.refused(lambda: self.assemble(None, **real), "OUTCOME_SPEC_REQUIRED", dv.DeliveryRefused)
        self.refused(lambda: self.assemble("cxp-osp-" + "1" * 64), "UNKNOWN_OUTCOME_SPEC", dv.DeliveryRefused)
        spec = self.propose()
        good = self.assemble(spec["spec_id"])
        orphan = self.package_event(spec, good, source_artifact_ids=[r["record_id"] for r in self.brief["initiating_records"]])
        receipt = self.x.ingest(orphan)
        self.assertEqual(receipt.error_code, cxp.E_TRANSITION_REFUSED)
        self.assertIn("absent from the package's source lineage", receipt.detail)
        real_payload = {**self.x.get_record(good["package_record_id"]).payload(), **real, "outcome_spec_id": None,
                        "source_artifact_ids": [r["record_id"] for r in self.brief["initiating_records"]],
                        "package_id": "cxp-dlv-" + "4" * 64}
        receipt = self.x.ingest(raw(cxp.KIND_DELIVERY_PACKAGE, real_payload, set(real_payload["source_artifact_ids"]),
                                    emitter=EDITOR))
        self.assertIn("requires an outcome specification", receipt.detail)

    def test_10_cross_customer_and_cross_project_substitution(self):
        spec = self.propose()
        self.refused(lambda: self.assemble(spec["spec_id"], customer_ref="customer-synthetic-other-shop"),
                     "OUTCOME_SPEC_MISMATCH:customer_ref", dv.DeliveryRefused)
        self.refused(lambda: self.assemble(spec["spec_id"], project_ref="project-synthetic-other-project"),
                     "OUTCOME_SPEC_MISMATCH:project_ref", dv.DeliveryRefused)
        good = self.assemble(spec["spec_id"])
        for field, value in (("customer_ref", "customer-synthetic-other-shop"),
                             ("project_ref", "project-synthetic-other-project")):
            with self.subTest(field):
                receipt = self.x.ingest(self.package_event(spec, good, **{field: value}))
                self.assertEqual(receipt.error_code, cxp.E_TRANSITION_REFUSED)
                self.assertIn(f"{field} differs", receipt.detail)
        unbound = self.x.ingest(self.package_event(spec, good, outcome_spec_id=None))
        self.assertIn("not bound to", unbound.detail)
        other = self.propose(customer_ref="customer-synthetic-other-shop")
        swapped = self.package_event(spec, good, outcome_spec_id=other["spec_id"])
        self.assertEqual(self.x.ingest(swapped).error_code, cxp.E_TRANSITION_REFUSED)

    def test_11_synthetic_real_mismatch_is_refused(self):
        real = dict(project_ref="project-intake-diagnostic", customer_ref="customer-northwind-repairs", synthetic=False)
        real_spec = self.propose(**real, disclosures=["Delay durations are unmeasured."])
        self.refused(lambda: self.assemble(real_spec["spec_id"]), "OUTCOME_SPEC_MISMATCH", dv.DeliveryRefused)
        synthetic_spec = self.propose()
        self.refused(lambda: self.assemble(synthetic_spec["spec_id"], **real), "OUTCOME_SPEC_MISMATCH:synthetic",
                     dv.DeliveryRefused)
        good = self.assemble(synthetic_spec["spec_id"])
        flipped = self.x.ingest(self.package_event(synthetic_spec, good, synthetic=False))
        self.assertNotEqual(flipped.status, exchange.ACCEPTED)


class TestDestination(ODCCTestCase):
    def test_12_failed_criterion_gives_exact_bounded_revision_candidate(self):
        spec = self.propose()
        v1 = self.assemble(spec["spec_id"], artifacts=solution(with_plan=False))
        self.assertEqual(self.desk.status(v1["package_id"])["status"], dv.DRAFT)
        rc = self.outcomes.revision_candidate(v1["package_id"])["candidate"]
        self.assertEqual([f["criterion_id"] for f in rc["failed_criteria"]], ["ac-validation-plan"])
        self.assertEqual(rc["must_keep"]["criteria_sha256"], spec["spec"]["criteria_sha256"])
        self.assertEqual((rc["must_keep"]["outcome_spec_id"], rc["next_version"], rc["criteria_may_change"]),
                         (spec["spec_id"], 2, False))
        report = self.outcomes.report(v1["package_id"])
        self.assertFalse(report["stages"][ds.TECHNICAL_COMPLETION]["established"])
        v2 = self.assemble(spec["spec_id"], predecessor_package_id=v1["package_id"], created_at=T[3])
        self.assertEqual(self.desk.status(v2["package_id"])["status"], dv.VALIDATED)
        self.assertEqual(self.outcomes.revision_candidate(v1["package_id"])["reason"], "ALREADY_REVISED")
        self.assertEqual(self.outcomes.revision_candidate(v2["package_id"])["reason"], "NO_REVISION_INDICATED")
        other = self.propose(acceptance_criteria=CRITERIA[:2] + CRITERIA[3:])
        self.refused(lambda: self.assemble(other["spec_id"], predecessor_package_id=v2["package_id"], created_at=T[4],
                                           acceptance_criteria=CRITERIA[:2] + CRITERIA[3:]),
                     "outcome spec", dv.DeliveryRefused)

    def test_13_read_only_methods_never_write(self):
        spec = self.propose()
        v1 = self.assemble(spec["spec_id"], artifacts=solution(with_plan=False))
        before = snapshot(self.root)
        self.outcomes.revision_candidate(v1["package_id"])
        self.outcomes.report(v1["package_id"], engagement_ref=ENG)
        self.outcomes.promotion_candidate(OFFER)
        self.make_brief()
        self.assertEqual(snapshot(self.root), before)

    def test_14_customer_revision_request_starts_nothing(self):
        spec = self.propose()
        pkg = self.assemble(spec["spec_id"])
        self.through_delivery(pkg["package_id"])
        evidence = self.customer_outcome(pkg["package_id"], dv.CUSTOMER_REVISION_REQUESTED,
                                         "Revision requested: please add measured delays.")
        governor_before = snapshot(self.root / "governor") | snapshot(self.root / "artifacts")
        rc = self.outcomes.revision_candidate(pkg["package_id"])["candidate"]
        self.assertEqual([t["trigger"] for t in rc["triggers"]], [dv.CUSTOMER_REVISION_REQUESTED])
        self.assertIn(evidence, rc["triggers"][0]["evidence"])
        report = self.outcomes.report(pkg["package_id"])
        self.assertEqual(report["return_path"], {"customer_evidence_record_ids": [evidence],
                                                 "eligible_as": "a new ORIGIN input, only through CycleRunner and the R4 governor",
                                                 "started_automatically": False})
        self.assertEqual(snapshot(self.root / "governor") | snapshot(self.root / "artifacts"), governor_before)
        echo = self.accept(ev.claim([pkg["package_record_id"]], statement="Delivered, so the diagnosis is right.",
                                    evidence=cxp.EV_NONE))
        decision = self.runner.run([], TOPIC, T[8], extra_input_ids=[echo])["governor_decision"]
        # our own output never re-enters unattended; R4 names the commercial lineage first, then recycling
        self.assertEqual(decision["decision"], gv.NEEDS_HUMAN)
        self.assertIn(decision["reason_code"], gv.APPROVABLE_REASONS)

    def test_15_16_no_payment_or_value_without_evidence(self):
        spec = self.propose()
        pkg = self.assemble(spec["spec_id"])
        self.through_delivery(pkg["package_id"])
        self.customer_outcome(pkg["package_id"], dv.CUSTOMER_ACCEPTED, "We accept this diagnostic.")
        for engagement in (None, ENG):
            with self.subTest(engagement=engagement):
                stages = self.outcomes.report(pkg["package_id"], engagement_ref=engagement)["stages"]
                self.assertEqual([stages[s]["established"] for s in ds.STAGES],
                                 [True, True, True, True, False, False, False, False])
        # a recorded-but-unverified payment is still not confirmed revenue
        for stage, extra in ((cm.PROPOSAL_SENT, dict(offer_ref=OFFER, document_digest="sha256:" + "a" * 64)),
                             (cm.CONTRACT_SIGNED, dict(offer_ref=OFFER, document_digest="sha256:" + "b" * 64)),
                             (cm.PAYMENT_CONFIRMED, dict(payment_reference_digest="sha256:" + "c" * 64))):
            self.accept(signal(stage, engagement=ENG, account=ACCT, amount={"minor": 500000, "currency": "USD"}, **extra))
        stages = self.outcomes.report(pkg["package_id"], engagement_ref=ENG)["stages"]
        self.assertFalse(stages[ds.PAYMENT_CONFIRMED]["established"])
        self.assertIn(cm.REVENUE_UNVERIFIED_CLAIM, stages[ds.PAYMENT_CONFIRMED]["basis"])
        self.assertEqual(self.outcomes.report(pkg["package_id"])["value_hypotheses"][0]["status"], "HYPOTHESIS_NOT_REVENUE")

    def test_17_repeatability_never_becomes_promotion(self):
        spec = self.propose()
        pkg = self.assemble(spec["spec_id"])
        fake = {"status": cm.REPEATABILITY_CANDIDATE, "independent_buyers": 3, "minimum_independent_buyers": 3,
                "qualifying_engagements": ["eng-a", "eng-b", "eng-c"]}
        with mock.patch.object(cm, "repeatability", return_value=fake):
            candidate = self.outcomes.promotion_candidate(OFFER)
            stages = self.outcomes.report(pkg["package_id"])["stages"]
        self.assertEqual((candidate["repeatability_status"], candidate["capability_promoted"]),
                         (cm.REPEATABILITY_CANDIDATE, False))
        self.assertTrue(candidate["promotion_gate"].startswith("UNAVAILABLE"))
        self.assertTrue(stages[ds.REPEATABILITY_CANDIDATE]["established"])
        self.assertFalse(stages[ds.CAPABILITY_PROMOTED]["established"])
        self.assertFalse(any("promote" in n.lower() and n != "promotion_candidate" for n in dir(ds.OutcomeDesk)))

    def test_18_replay_and_restart_reproduce_reports(self):
        spec = self.propose()
        v1 = self.assemble(spec["spec_id"], artifacts=solution(with_plan=False))
        v2 = self.assemble(spec["spec_id"], predecessor_package_id=v1["package_id"], created_at=T[3])
        self.through_delivery(v2["package_id"])
        self.customer_outcome(v2["package_id"], dv.CUSTOMER_ACCEPTED, "We accept this diagnostic.")
        before = ([self.outcomes.report(p, engagement_ref=ENG) for p in (v1["package_id"], v2["package_id"])],
                  [self.outcomes.revision_candidate(p) for p in (v1["package_id"], v2["package_id"])],
                  self.make_brief(), self.outcomes.spec(spec["spec_id"]))
        self.boot(self.root)  # fresh exchange, governor, runner and desks over the same files
        after = ([self.outcomes.report(p, engagement_ref=ENG) for p in (v1["package_id"], v2["package_id"])],
                 [self.outcomes.revision_candidate(p) for p in (v1["package_id"], v2["package_id"])],
                 self.make_brief(), self.outcomes.spec(spec["spec_id"]))
        self.assertEqual(after, before)

    def test_19_r2a_compatibility(self):
        intake = self.brief["initiating_records"][0]["record_id"]
        legacy = self.desk.assemble(project_ref=PROJECT, customer_ref=CUSTOMER, synthetic=True, editor_id=EDITOR,
                                    artifacts=solution(), source_artifact_ids=[intake],
                                    acceptance_criteria=copy.deepcopy(CRITERIA), known_limitations=[], created_at=T[2])
        self.assertEqual(self.desk.status(legacy["package_id"])["status"], dv.VALIDATED)  # synthetic: spec optional
        self.assertIsNone(self.outcomes.report(legacy["package_id"])["outcome_spec"]["spec_id"])
        r2a_shaped = {k: v for k, v in self.x.get_record(legacy["package_record_id"]).payload().items()
                      if k not in ("outcome_spec_id", "criteria_sha256")}
        r2a_shaped["package_id"] = "cxp-dlv-" + "5" * 64
        receipt = self.x.ingest(raw(cxp.KIND_DELIVERY_PACKAGE, r2a_shaped, [intake], emitter=EDITOR))
        self.assertEqual(receipt.status, exchange.ACCEPTED)  # R2a-shaped records still parse
        real = {**r2a_shaped, "project_ref": "project-intake-diagnostic", "customer_ref": "customer-northwind-repairs",
                "synthetic": False, "package_id": "cxp-dlv-" + "6" * 64}
        self.assertEqual(self.x.ingest(raw(cxp.KIND_DELIVERY_PACKAGE, real, [intake], emitter=EDITOR)).error_code,
                         cxp.E_TRANSITION_REFUSED)
        self.boot(self.root)
        self.assertEqual(self.desk.status(legacy["package_id"])["status"], dv.VALIDATED)

    def test_specs_are_never_research_input(self):
        spec = self.propose()
        echo = self.accept(ev.claim([spec["spec_record_id"]], statement="The spec says it, so it is so.",
                                    evidence=cxp.EV_NONE))
        decision = self.runner.run([], TOPIC, T[8], extra_input_ids=[echo])["governor_decision"]
        self.assertEqual(decision["decision"], gv.NEEDS_HUMAN)
        self.assertIn(decision["reason_code"], gv.APPROVABLE_REASONS)
        self.assertFalse(self.outcomes.grants_execution_authority)
        source = Path(ds.__file__).read_text() + Path(origin.__file__).read_text()
        for word in ("import socket", "import subprocess", "urllib", "smtplib", "def send", "def publish", "def pay"):
            self.assertNotIn(word, source)


if __name__ == "__main__":
    unittest.main()
