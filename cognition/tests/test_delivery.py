"""R2a governed delivery package tests. Synthetic fixtures; temporary
stores; no network, upload, email, payment or platform access."""
import copy
import json
import os
import stat
from pathlib import Path

from cognition import bundle, commerce, coordinator as co, cxp, delivery as dv, episode as ep, exchange
from cognition import governor as gv, handoff as hf, package_revision as rv, production as pr
from cognition.tests import _events as ev
from cognition.tests._commerce_events import signal
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_handoff import SIGNER, HandoffTestCase

EDITOR_D, REVIEWER_D, SIGNER_D, COURIER = "operator-delivery-editor", "operator-qa-lead", "operator-account-lead", "operator-courier"
T0, T1, T2, T3, T4, T5 = (f"2026-10-18T1{h}:00:00Z" for h in range(4, 10))
PROJECT, CUSTOMER = "project-synthetic-intake-diagnostic", "customer-synthetic-northwind-repairs"

REPORT = (b"# Workflow-loss diagnostic (SYNTHETIC FIXTURE)\n\n"
          b"## Current state\nRequests arrive by phone and web form; assignment happens in a weekly meeting.\n\n"
          b"## Bottlenecks\n1. No owner between first contact and assignment.\n\n"
          b"## Uncertainty register\n- Delay durations are unmeasured; no real customer data was used.\n")
FINDINGS = b"stage,observed_delay,evidence\nintake_to_assignment,unmeasured,synthetic_fixture\n"
CRITERIA = [
    {"criterion_id": "ac-report-present", "check": "artifact_present", "path": "report.md",
     "description": "The diagnostic report is included"},
    {"criterion_id": "ac-uncertainty-register", "check": "contains_text", "path": "report.md",
     "text": "## Uncertainty register", "description": "The report carries an uncertainty register"},
    {"criterion_id": "ac-findings-present", "check": "artifact_present", "path": "findings.csv",
     "description": "The findings table is included"},
    {"criterion_id": "ac-reviewer-reads-report", "check": "human_judgement",
     "description": "A reviewer has read the report end to end"},
]


def digest(data: bytes) -> str:
    return "sha256:" + bundle.sha256_hex(data)


class DeliveryTestCase(HandoffTestCase):
    def setUp(self):
        super().setUp()
        self.desk = dv.DeliveryDesk(self.x, self.g, self.tmp / "a" / "deliveries")
        self.intake = self.accept(ev.observation(
            statement="Synthetic intake: requests are lost between first contact and staff assignment.",
            sources=[ev.source("synthetic:intake/northwind-001")]))

    def generic(self, **overrides):
        kwargs = dict(project_ref=PROJECT, customer_ref=CUSTOMER, synthetic=True, editor_id=EDITOR_D,
                      artifacts={"report.md": REPORT, "findings.csv": FINDINGS}, source_artifact_ids=[self.intake],
                      acceptance_criteria=copy.deepcopy(CRITERIA),
                      known_limitations=["Synthetic fixture; no customer data was collected."], created_at=T0)
        kwargs.update(overrides)
        return self.desk.assemble(**kwargs)

    def approve_delivery(self, package_id, at=T1):
        meta = next(m for m in self.x.all_record_metadata() if m.get("delivery_package", {}).get("package_id") == package_id)
        self.desk.review(package_id, REVIEWER_D, ep.APPROVED, at,
                         criteria_judged=meta["delivery_package"]["human_judgement_criteria"])  # exactly the human criteria

    def through_delivery(self, package_id):
        self.approve_delivery(package_id)
        self.desk.sign_handoff(package_id, SIGNER_D, T2)
        self.desk.record_delivery(package_id, COURIER, dv.CHANNEL_SYNTHETIC, T3)

    def customer_words(self, package_id, words="We accept this diagnostic as delivered.", customer=CUSTOMER,
                       synthetic=True, **labels):
        source = ev.source(f"customer:{customer}/{package_id}/reply-001",
                           source_type="synthetic_fixture" if synthetic else "document")
        return self.accept(ev.observation(statement=words, sources=[source], **labels))

    def refused(self, fn, expected):
        before = snapshot(self.tmp / "a")
        with self.assertRaises(dv.DeliveryRefused) as ctx:
            fn()
        self.assertTrue(any(expected in r for r in ctx.exception.reasons), ctx.exception.reasons)
        self.assertEqual(snapshot(self.tmp / "a"), before)
        return ctx.exception

    def writable(self, path):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return path


class TestConstruction(DeliveryTestCase):
    def test_generic_non_video_package(self):
        out = self.generic()
        body, directory = out["delivery"], Path(out["directory"])
        for field in ("project_ref", "customer_ref", "synthetic", "source_artifact_ids", "artifact_manifest",
                      "checksums", "acceptance_criteria", "validation_results", "known_limitations",
                      "predecessor_package_id", "created_at", "editor_id"):
            self.assertIn(field, body)
        self.assertEqual(out["package_id"], cxp.digest_id("delivery", body))
        self.assertTrue(out["package_id"].startswith("cxp-dlv-"))
        self.assertEqual(sorted(bundle.read(directory)), ["SHA256SUMS", "artifacts/findings.csv", "artifacts/report.md",
                                                          "delivery.json"])
        manifest = {a["path"]: a for a in body["artifact_manifest"]}
        self.assertEqual(manifest["artifacts/report.md"]["sha256"], bundle.sha256_hex(REPORT))
        self.assertEqual((manifest["artifacts/report.md"]["media_type"], manifest["artifacts/findings.csv"]["media_type"]),
                         ("text/markdown", "text/csv"))
        listed = bundle.parse_sums((directory / "SHA256SUMS").read_bytes())
        for path, data in bundle.read(directory).items():
            if path != "SHA256SUMS":
                self.assertEqual(listed[path], bundle.sha256_hex(data))
                self.assertFalse(os.stat(directory / path).st_mode & 0o222, path)
        self.assertEqual([r["result"] for r in body["validation_results"]], [dv.PASS, dv.PASS, dv.PASS, dv.HUMAN])
        self.assertEqual(body["statements"], {"delivery_is_not_acceptance": True, "acceptance_is_not_payment": True,
                                              "identities_are_not_authenticated": True, "publication_authorized": False})
        record = self.x.get_record(out["package_record_id"])
        self.assertEqual((record.kind, record.provenance, record.evidence, record.verification),
                         (cxp.KIND_DELIVERY_PACKAGE, cxp.HUMAN_ASSERTED, cxp.EV_NONE, cxp.VER_UNVERIFIED))
        self.assertEqual(record.payload()["sums_sha256"], bundle.sha256_hex((directory / "SHA256SUMS").read_bytes()))
        status = self.desk.status(out["package_id"])
        self.assertEqual((status["status"], status["intact"], status["current"], status["reviewer_id"], status["signer_id"]),
                         (dv.VALIDATED, True, True, None, None))
        self.assertNotIn("youtube", Path(dv.__file__).read_text().lower())

    def test_production_handoff_is_the_first_consumer(self):
        h = self.export()
        inputs = self.exporter.package_inputs(h["handoff_id"])
        out = self.desk.assemble(project_ref="project-synthetic-episode-001",
                                 customer_ref="customer-synthetic-production-team", synthetic=True,
                                 editor_id=EDITOR_D, created_at=T0, **inputs)
        directory = Path(out["directory"])
        for name in hf.BUNDLE_FILES:  # byte-exact copies of the R1 bundle
            self.assertEqual((directory / "artifacts" / name).read_bytes(), (Path(h["directory"]) / name).read_bytes())
        self.assertEqual(out["delivery"]["source_artifact_ids"], [h["handoff_record_id"]])
        self.assertEqual(self.desk.status(out["package_id"])["status"], dv.VALIDATED)
        self.through_delivery(out["package_id"])
        self.assertEqual(self.desk.status(out["package_id"])["status"], dv.DELIVERED)

    def test_stale_or_tampered_handoff_is_not_deliverable(self):
        h = self.export()
        self.revise([{"op": "set_audio", "scene_id": self.scene[pr.DRAMATIZATION]["scene_id"],
                      "music": "silence", "pacing": "slow"}], self.v2["package_id"], at="2026-10-18T13:30:00Z")
        with self.assertRaises(hf.HandoffRefused) as ctx:
            self.exporter.package_inputs(h["handoff_id"])
        self.assertIn(f"HANDOFF_NOT_DELIVERABLE:{hf.STALE}", ctx.exception.reasons)

    def test_malformed_references_and_missing_artifacts(self):
        cases = {
            "MALFORMED_PROJECT_REF": dict(project_ref="Northwind Project"),
            "MALFORMED_CUSTOMER_REF": dict(customer_ref="northwind@example.com"),
            "SYNTHETIC_FLAG_REQUIRED": dict(synthetic="yes"),
            "MISSING_ARTIFACT:report.md": dict(artifacts={"report.md": None, "findings.csv": FINDINGS}),
            "ARTIFACTS_REQUIRED": dict(artifacts={}),
            "INVALID_ARTIFACT_NAME:../escape.md": dict(artifacts={"../escape.md": REPORT}),
            "MISSING_SOURCE_ARTIFACT": dict(source_artifact_ids=["cxp-rec-" + "9" * 64]),
            "SOURCE_ARTIFACTS_REQUIRED": dict(source_artifact_ids=[]),
            "ACCEPTANCE_CRITERIA_REQUIRED": dict(acceptance_criteria=[]),
            "UNKNOWN_CRITERION_CHECK": dict(acceptance_criteria=[{"criterion_id": "ac-x", "check": "llm_says_ok",
                                                                  "description": "x"}]),
            "TEXT_REFUSED": dict(known_limitations=["Call the owner on 555 123 4567 8"]),
            "UNAUTHORIZED_EDITOR": dict(editor_id="delivery-bot"),
        }
        for reason, override in cases.items():
            with self.subTest(reason):
                self.refused(lambda: self.generic(**override), reason)

    def test_failed_machine_check_is_draft_and_cannot_be_approved(self):
        out = self.generic(artifacts={"report.md": b"# Report without the register\n", "findings.csv": FINDINGS})
        status = self.desk.status(out["package_id"])
        self.assertEqual(status["status"], dv.DRAFT)
        self.refused(lambda: self.desk.review(out["package_id"], REVIEWER_D, ep.APPROVED, T1,
                                              criteria_judged=["ac-reviewer-reads-report"]),
                     "machine acceptance checks failed")
        self.desk.review(out["package_id"], REVIEWER_D, ep.NEEDS_REVISION, T1, notes="Add the uncertainty register.")
        self.assertEqual(self.desk.status(out["package_id"])["status"], dv.RETURNED_FOR_REVISION)

    def test_identical_assembly_is_idempotent(self):
        first, second = self.generic(), self.generic()
        self.assertEqual((first["package_id"], first["package_record_id"]),
                         (second["package_id"], second["package_record_id"]))


class TestLifecycle(DeliveryTestCase):
    def test_full_synthetic_lifecycle(self):
        out = self.generic()
        pid = out["package_id"]
        self.approve_delivery(pid)
        self.assertEqual(self.desk.status(pid)["status"], dv.VALIDATED)  # approval alone is not handoff
        self.desk.sign_handoff(pid, SIGNER_D, T2)
        self.assertEqual(self.desk.status(pid)["status"], dv.APPROVED_FOR_HANDOFF)
        self.desk.record_delivery(pid, COURIER, dv.CHANNEL_SYNTHETIC, T3)
        status = self.desk.status(pid)
        self.assertEqual((status["status"], status["customer_outcome"], status["delivery"]["receipt_confirmed_by_customer"]),
                         (dv.DELIVERED, None, False))
        words = "We accept this diagnostic as delivered."
        evidence = self.customer_words(pid, words)
        self.desk.record_customer_outcome(pid, COURIER, dv.CUSTOMER_ACCEPTED, evidence, digest(words.encode()), T4)
        status = self.desk.status(pid)
        self.assertEqual((status["status"], status["editor_id"], status["reviewer_id"], status["signer_id"]),
                         (dv.ACCEPTED, EDITOR_D, REVIEWER_D, SIGNER_D))
        self.assertEqual([h["event"] for h in status["history"]],
                         [dv.REVIEW_APPROVED, dv.HANDOFF_SIGNED, dv.EV_DELIVERED, dv.CUSTOMER_ACCEPTED])
        self.assertEqual((status["payment_recorded"], status["publication_authorized"], status["identities_authenticated"]),
                         (False, False, False))
        # no commercial fact was inferred: commerce has nothing to report
        self.assertFalse([m for m in self.x.all_record_metadata() if m["kind"] == cxp.KIND_COMMERCIAL_SIGNAL])
        self.assertFalse(hasattr(commerce, "DeliveryDesk"))

    def test_rejection_and_revision_request_outcomes(self):
        for outcome, expected in ((dv.CUSTOMER_REJECTED, dv.REJECTED),
                                  (dv.CUSTOMER_REVISION_REQUESTED, dv.REVISION_REQUESTED)):
            with self.subTest(outcome):
                out = self.generic(created_at=T0 if outcome == dv.CUSTOMER_REJECTED else T5)
                self.through_delivery(out["package_id"])
                words = f"Outcome {outcome.lower()}: the findings table needs measured delays."
                evidence = self.customer_words(out["package_id"], words)
                self.desk.record_customer_outcome(out["package_id"], COURIER, outcome, evidence,
                                                  digest(words.encode()), T4)
                self.assertEqual(self.desk.status(out["package_id"])["status"], expected)

    def test_unsupported_transitions(self):
        pid = self.generic()["package_id"]
        words = "We accept it."
        evidence = self.customer_words(pid, words)
        self.refused(lambda: self.desk.sign_handoff(pid, SIGNER_D, T2), "needs an approving review")
        self.refused(lambda: self.desk.record_delivery(pid, COURIER, dv.CHANNEL_SYNTHETIC, T3), "needs a signed handoff")
        self.refused(lambda: self.desk.record_customer_outcome(pid, COURIER, dv.CUSTOMER_ACCEPTED, evidence,
                                                               digest(words.encode()), T4), "needs a recorded delivery")
        self.approve_delivery(pid)
        self.refused(lambda: self.desk.review(pid, "operator-second-reviewer", ep.REJECTED, T2), "already been reviewed")
        self.refused(lambda: self.desk.record_delivery(pid, COURIER, dv.CHANNEL_SYNTHETIC, T3), "needs a signed handoff")
        self.refused(lambda: self.desk.review(pid, REVIEWER_D, "MAYBE", T2), "UNKNOWN_DECISION")

    def test_unapproved_handoff(self):
        pid = self.generic()["package_id"]
        self.desk.review(pid, REVIEWER_D, ep.NEEDS_REVISION, T1)
        self.refused(lambda: self.desk.sign_handoff(pid, SIGNER_D, T2), "needs an approving review")
        other = self.generic(created_at=T5)["package_id"]
        self.refused(lambda: self.desk.review(other, REVIEWER_D, ep.APPROVED, T1, criteria_judged=[]),
                     "judge exactly the package's human-judgement criteria")

    def test_editor_signer_and_reviewer_separation(self):
        pid = self.generic()["package_id"]
        self.refused(lambda: self.desk.review(pid, EDITOR_D, ep.APPROVED, T1,
                                              criteria_judged=["ac-reviewer-reads-report"]), "editor of a package version cannot review")
        self.approve_delivery(pid)
        self.refused(lambda: self.desk.sign_handoff(pid, EDITOR_D, T2), "editor of a package version cannot sign")
        for person in ("delivery-bot", "Jane Signer", None):
            with self.subTest(person):
                self.refused(lambda: self.desk.sign_handoff(pid, person, T2), "UNAUTHORIZED_ACTOR")
        with self.g.running():
            self.refused(lambda: self.desk.sign_handoff(pid, SIGNER_D, T2), "ACTOR_DURING_RUNNING_CYCLE")

    def test_duplicate_records(self):
        pid = self.generic()["package_id"]
        self.approve_delivery(pid)
        before = self.desk.status(pid)
        meta = next(m for m in self.x.all_record_metadata() if m.get("delivery_event"))
        replay = self.x.get_record(meta["record_id"])
        raw = {"schema_version": 1, "kind": replay.kind, "representation": replay.representation,
               "evidence": replay.evidence, "verification": replay.verification, "provenance": replay.provenance,
               "privacy": replay.privacy, "payload": replay.payload(), "sources": [],
               "derived_from": list(replay.derived_from), "verification_ref": None, "consent_ref": None,
               "occurrence": {"emitter_id": REVIEWER_D, "observed_at": T5}}
        self.assertEqual(self.x.ingest(raw).status, exchange.DUPLICATE_RECORD)
        self.assertEqual(self.desk.status(pid), before)
        second = copy.deepcopy(raw)
        second["payload"]["notes"] = "Approving again, louder."
        receipt = self.x.ingest(second)
        self.assertEqual((receipt.status, receipt.error_code), ("REJECTED", cxp.E_TRANSITION_REFUSED))


class TestRevisionAndSupersession(DeliveryTestCase):
    def revise_delivery(self, predecessor, **overrides):
        return self.generic(predecessor_package_id=predecessor, created_at=T5,
                            artifacts={"report.md": REPORT + b"\n## Revision\nAdded owner proposal.\n",
                                       "findings.csv": FINDINGS}, **overrides)

    def test_modification_after_approval_needs_fresh_authorization(self):
        v1 = self.generic()["package_id"]
        self.approve_delivery(v1)
        self.desk.sign_handoff(v1, SIGNER_D, T2)
        v2 = self.revise_delivery(v1)
        self.assertEqual((v2["delivery"]["version"], v2["delivery"]["predecessor_package_id"]), (2, v1))
        old, new = self.desk.status(v1), self.desk.status(v2["package_id"])
        self.assertEqual((old["current"], old["superseded_by"], old["recorded_status"]),
                         (False, v2["package_id"], dv.APPROVED_FOR_HANDOFF))
        self.assertEqual((new["status"], new["reviewer_id"], new["signer_id"]), (dv.VALIDATED, None, None))
        self.refused(lambda: self.desk.record_delivery(v1, COURIER, dv.CHANNEL_SYNTHETIC, T3), "superseded")
        record = self.x.get_record(v2["package_record_id"])
        self.assertIn(self.x.get_record(old["package_record_id"]).record_id, record.derived_from)

    def test_revision_lineage_rules(self):
        v1 = self.generic()["package_id"]
        v2 = self.revise_delivery(v1)["package_id"]
        self.refused(lambda: self.revise_delivery(v1), "PREDECESSOR_SUPERSEDED")
        self.refused(lambda: self.revise_delivery(v2, customer_ref="customer-synthetic-other-shop"),
                     "REVISION_CHANGES_PROJECT_CUSTOMER_OR_SYNTHETIC_FLAG")
        self.refused(lambda: self.revise_delivery("cxp-dlv-" + "0" * 64), "UNKNOWN_PREDECESSOR")
        self.assertEqual(self.desk.status(v2)["version"], 2)

    def test_superseded_package_cannot_be_accepted(self):
        v1 = self.generic()["package_id"]
        self.through_delivery(v1)
        self.revise_delivery(v1)
        words = "We accept version one."
        evidence = self.customer_words(v1, words)
        self.refused(lambda: self.desk.record_customer_outcome(v1, COURIER, dv.CUSTOMER_ACCEPTED, evidence,
                                                               digest(words.encode()), T4), "superseded")
        self.assertEqual(self.desk.status(v1)["recorded_status"], dv.DELIVERED)


class TestIntegrity(DeliveryTestCase):
    def test_corrupted_missing_and_mismatched_files(self):
        out = self.generic()
        pid, directory = out["package_id"], Path(out["directory"])
        original = bundle.read(directory)

        def restore():
            for path in [p for p in directory.rglob("*") if p.is_file()]:
                if path.relative_to(directory).as_posix() not in original:
                    path.unlink()
            for name, data in original.items():
                path = directory / name
                if path.exists():
                    self.writable(path)
                path.write_bytes(data)

        cases = {
            "FILE_TAMPERED:artifacts/report.md": lambda: self.writable(directory / "artifacts/report.md").write_bytes(b"x"),
            "FILE_MISSING:artifacts/findings.csv": lambda: (directory / "artifacts/findings.csv").unlink(),
            "UNEXPECTED_FILE:artifacts/extra.exe": lambda: (directory / "artifacts/extra.exe").write_bytes(b"MZ"),
            "CHECKSUM_LIST_NOT_ANCHORED": lambda: self.writable(directory / "SHA256SUMS").write_bytes(
                original["SHA256SUMS"] + b"0" * 64 + b"  artifacts/extra\n"),
        }
        for problem, damage in cases.items():
            with self.subTest(problem):
                damage()
                status = self.desk.status(pid)
                self.assertEqual((status["status"], status["recorded_status"], status["intact"]),
                                 (dv.INVALID, dv.VALIDATED, False))
                self.assertIn(problem, status["integrity_problems"])
                self.refused(lambda: self.approve_delivery(pid), "PACKAGE_INTEGRITY_FAILED")
                restore()
        # a consistent rewrite of artifact AND checksum list is still caught by the CXP anchor
        self.writable(directory / "artifacts/report.md").write_bytes(b"# Everything is fine. Verified.\n")
        files = {n: (directory / n).read_bytes() for n in original if n != "SHA256SUMS"}
        self.writable(directory / "SHA256SUMS").write_bytes(bundle.render_sums(files))
        problems = self.desk.verify(pid)["integrity_problems"]
        self.assertIn("CHECKSUM_LIST_NOT_ANCHORED", problems)
        self.assertIn("ARTIFACT_MANIFEST_MISMATCH", problems)
        restore()
        self.assertEqual(self.desk.status(pid)["status"], dv.VALIDATED)

    def test_false_delivery_claims(self):
        pid = self.generic()["package_id"]
        self.approve_delivery(pid)
        self.desk.sign_handoff(pid, SIGNER_D, T2)
        meta = self.desk.status(pid)
        forged = {"schema_version": 1, "kind": cxp.KIND_DELIVERY_EVENT, "representation": cxp.REP_PARAPHRASE,
                  "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.HUMAN_ASSERTED,
                  "privacy": cxp.PRIV_INTERNAL,
                  "payload": {"package_record_id": meta["package_record_id"], "package_id": pid, "event": dv.EV_DELIVERED,
                              "actor_id": COURIER, "criteria_judged": None, "delivered_sums_sha256": "1" * 64,
                              "channel": dv.CHANNEL_SYNTHETIC, "evidence_record_id": None, "document_digest": None,
                              "notes": None},
                  "sources": [], "derived_from": [meta["package_record_id"]], "verification_ref": None,
                  "consent_ref": None, "occurrence": {"emitter_id": COURIER, "observed_at": T3}}
        receipt = self.x.ingest(forged)
        self.assertEqual(receipt.error_code, cxp.E_TRANSITION_REFUSED)
        self.assertIn("not the one anchored", receipt.detail)
        self.refused(lambda: self.desk.record_delivery(pid, COURIER, dv.CHANNEL_MANUAL, T3), "SYNTHETIC_FIXTURE channel")
        self.writable(Path(self.desk.root / pid / "artifacts/report.md")).write_bytes(b"swapped before sending")
        self.refused(lambda: self.desk.record_delivery(pid, COURIER, dv.CHANNEL_SYNTHETIC, T3), "PACKAGE_INTEGRITY_FAILED")
        self.assertEqual(self.desk.status(pid)["recorded_status"], dv.APPROVED_FOR_HANDOFF)


class TestCustomerEvidence(DeliveryTestCase):
    def setUp(self):
        super().setUp()
        self.pid = self.generic()["package_id"]
        self.through_delivery(self.pid)
        self.words = "We accept this diagnostic as delivered."

    def outcome(self, evidence):
        return lambda: self.desk.record_customer_outcome(self.pid, COURIER, dv.CUSTOMER_ACCEPTED, evidence,
                                                         digest(self.words.encode()), T4)

    def test_fabricated_acceptance(self):
        operator_says = self.customer_words(self.pid, self.words, provenance=cxp.HUMAN_ASSERTED)
        self.refused(self.outcome(operator_says), "operator assertion is not customer evidence")
        paraphrased = self.customer_words(self.pid, "They seemed happy with it.", representation=cxp.REP_PARAPHRASE)
        self.refused(self.outcome(paraphrased), "observed and quoted")
        other_customer = self.customer_words(self.pid, self.words, customer="customer-synthetic-someone-else")
        self.refused(self.outcome(other_customer), "located at customer:")
        other_version = self.accept(ev.observation(statement=self.words, sources=[
            ev.source(f"customer:{CUSTOMER}/cxp-dlv-{'5' * 64}/reply-001")]))
        self.refused(self.outcome(other_version), "located at customer:")
        real_shaped = self.customer_words(self.pid, self.words, synthetic=False)
        self.refused(self.outcome(real_shaped), "synthetic_fixture source")
        self.refused(self.outcome(self.intake), "located at customer:")  # the intake record is not an acceptance
        self.assertEqual(self.desk.status(self.pid)["status"], dv.DELIVERED)

    def test_acceptance_without_customer_evidence(self):
        self.refused(self.outcome(None), "SCHEMA_MALFORMED")
        self.refused(self.outcome("cxp-rec-" + "7" * 64), "LINEAGE")
        claim = self.accept(ev.claim([self.intake], statement="The customer accepted."))
        self.refused(self.outcome(claim), "recorded as an OBSERVATION")
        meta = self.desk.status(self.pid)
        forged = {"schema_version": 1, "kind": cxp.KIND_DELIVERY_EVENT, "representation": cxp.REP_PARAPHRASE,
                  "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.HUMAN_ASSERTED,
                  "privacy": cxp.PRIV_INTERNAL,
                  "payload": {"package_record_id": meta["package_record_id"], "package_id": self.pid,
                              "event": dv.CUSTOMER_ACCEPTED, "actor_id": COURIER, "criteria_judged": None,
                              "delivered_sums_sha256": None, "channel": None, "evidence_record_id": None,
                              "document_digest": digest(b"x"), "notes": None},
                  "sources": [], "derived_from": [meta["package_record_id"]], "verification_ref": None,
                  "consent_ref": None, "occurrence": {"emitter_id": COURIER, "observed_at": T4}}
        self.assertEqual(self.x.ingest(forged).error_code, cxp.E_MALFORMED)
        promoted = copy.deepcopy(forged)
        promoted.update(provenance=cxp.OBSERVED)
        promoted["payload"]["evidence_record_id"] = self.intake
        promoted["derived_from"] = sorted([meta["package_record_id"], self.intake])
        self.assertEqual(self.x.ingest(promoted).error_code, cxp.E_KIND_RULE)

    def test_synthetic_and_real_never_mix(self):
        real = dict(project_ref="project-intake-diagnostic", customer_ref="customer-northwind-repairs", synthetic=False)
        self.refused(lambda: self.generic(**{**real, "synthetic": True}), "SYNTHETIC_REFS_REQUIRED")
        self.refused(lambda: self.generic(synthetic=False), "SYNTHETIC_REF_ON_REAL_PACKAGE")
        self.refused(lambda: self.generic(**real), "OUTCOME_SPEC_REQUIRED")  # ODCC-1: real packages bind a spec
        from cognition import destination, origin
        brief = origin.origin_brief(self.x, self.runner, self.artifact["artifact_id"], capability_registry={},
                                    required_tags=["analysis"])
        spec = destination.OutcomeDesk(self.x, self.runner, self.desk).propose(
            brief, intended_outcome="Show where requests are lost.", acceptance_criteria=copy.deepcopy(CRITERIA),
            required_deliverables=["findings.csv", "report.md"], disclosures=[], author_id="operator-account-lead",
            observed_at=T0, engagement_ref="eng-northwind-repairs",  # ENGAGE-1: real specs bind consent
            consent_record_id=self.accept(signal(commerce.INTEREST_CONFIRMED, engagement="eng-northwind-repairs",
                                                 account="acct-northwind-repairs", summary="Agreed to talk",
                                                 consent_ref="consent-eng-northwind-repairs")), **real)
        pid = self.generic(**real, outcome_spec_id=spec["spec_id"])["package_id"]  # real-shaped; no real customer
        self.approve_delivery(pid)
        self.desk.sign_handoff(pid, SIGNER_D, T2)
        self.refused(lambda: self.desk.record_delivery(pid, COURIER, dv.CHANNEL_SYNTHETIC, T3), "SYNTHETIC_FIXTURE channel")
        self.desk.record_delivery(pid, COURIER, dv.CHANNEL_MANUAL, T3)
        synthetic_words = self.customer_words(pid, self.words, customer="customer-northwind-repairs", synthetic=True)
        self.refused(lambda: self.desk.record_customer_outcome(pid, COURIER, dv.CUSTOMER_ACCEPTED, synthetic_words,
                                                               digest(self.words.encode()), T4), "document source")
        self.assertIs(self.desk.status(pid)["synthetic"], False)
        self.assertIs(self.desk.status(self.pid)["synthetic"], True)


class TestReplayAndBoundaries(DeliveryTestCase):
    def test_replay_and_restart_consistency(self):
        v1 = self.generic()["package_id"]
        self.through_delivery(v1)
        words = "Revision requested: add measured delays."
        self.desk.record_customer_outcome(v1, COURIER, dv.CUSTOMER_REVISION_REQUESTED, self.customer_words(v1, words),
                                          digest(words.encode()), T4)
        v2 = self.generic(predecessor_package_id=v1, created_at=T5,
                          artifacts={"report.md": REPORT + b"\nMeasured delays: pending.\n", "findings.csv": FINDINGS})
        before = {p: self.desk.status(p) for p in (v1, v2["package_id"])}
        restarted = exchange.CognitiveExchange(self.tmp / "a" / "store")
        desk = dv.DeliveryDesk(restarted, self.g, self.tmp / "a" / "deliveries")
        self.assertEqual({p: desk.status(p) for p in before}, before)
        self.assertEqual(before[v1]["recorded_status"], dv.REVISION_REQUESTED)
        self.assertEqual(before[v2["package_id"]]["status"], dv.VALIDATED)

    def test_deterministic_identity_across_stores(self):
        out = self.generic()
        other = dv.DeliveryDesk(self.x, self.g, self.tmp / "a" / "deliveries-copy")
        twin = other.assemble(project_ref=PROJECT, customer_ref=CUSTOMER, synthetic=True, editor_id=EDITOR_D,
                              artifacts={"findings.csv": FINDINGS, "report.md": REPORT}, source_artifact_ids=[self.intake],
                              acceptance_criteria=copy.deepcopy(CRITERIA),
                              known_limitations=["Synthetic fixture; no customer data was collected."], created_at=T0)
        self.assertEqual(twin["package_id"], out["package_id"])
        self.assertEqual(bundle.read(Path(twin["directory"])), bundle.read(Path(out["directory"])))

    def test_delivery_records_are_never_research_input(self):
        out = self.generic()
        self.approve_delivery(out["package_id"])
        for meta in [m for m in self.x.all_record_metadata() if m["kind"] in (cxp.KIND_DELIVERY_PACKAGE,
                                                                            cxp.KIND_DELIVERY_EVENT)]:
            with self.assertRaises(co.CoordinatorError):
                co.LensCoordinator(self.x).run([meta["record_id"]], "t", "2026-10-19T00:00:00Z")
        echo = self.accept(ev.claim([out["package_record_id"]], statement="It was packaged, so it works.",
                                    evidence=cxp.EV_NONE))
        decision = self.runner.run([], "t", "2026-10-19T00:00:00Z", extra_input_ids=[echo])["governor_decision"]
        self.assertEqual(decision["reason_code"], gv.R_RECYCLED)

    def test_no_delivery_payment_or_publication_surface(self):
        for obj in (dv.DeliveryDesk, dv):
            for name in dir(obj):
                for word in ("publish", "upload", "email", "smtp", "send", "invoice", "payment", "pay_", "charge"):
                    self.assertNotIn(word, name.lower(), name)
        source = Path(dv.__file__).read_text() + Path(bundle.__file__).read_text()
        for module in ("socket", "urllib", "http", "requests", "smtplib", "subprocess"):
            self.assertNotIn(f"import {module}", source)
        self.assertFalse(self.desk.grants_execution_authority)
