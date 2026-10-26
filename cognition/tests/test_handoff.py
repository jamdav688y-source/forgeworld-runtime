"""R1 production handoff tests. Synthetic fixtures; temporary stores; no
network, upload or platform access."""
import json
import os
import stat
from pathlib import Path
from unittest import mock

from cognition import coordinator as co, cxp, episode as ep, governor as gv, handoff as hf, production as pr
from cognition.tests import _events as ev
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_package_revision import EDITOR, T_EDIT, T_EDIT2, RevisionTestCase

REVIEWER, SIGNER = "operator-founder", "operator-production-lead"
T_REVIEW, T_SIGN, T_LATER = "2026-10-18T11:00:00Z", "2026-10-18T12:00:00Z", "2026-10-18T13:00:00Z"


class HandoffTestCase(RevisionTestCase):
    def setUp(self):
        super().setUp()
        self.v2 = self.revise(self.presentation_edits())
        self.editor.review(self.v2["package_id"], ep.APPROVED, REVIEWER, T_REVIEW)
        self.exporter = hf.HandoffExporter(self.editor, self.tmp / "a" / "handoffs")

    def export(self, package_id=None, signer=SIGNER, at=T_SIGN):
        return self.exporter.export(package_id or self.v2["package_id"], signer, at)

    def refused(self, expected, package_id=None, signer=SIGNER):
        before = snapshot(self.tmp / "a")
        with self.assertRaises(hf.HandoffRefused) as ctx:
            self.export(package_id, signer)
        self.assertTrue(any(expected in r for r in ctx.exception.reasons), ctx.exception.reasons)
        self.assertEqual(snapshot(self.tmp / "a"), before)  # nothing written, nothing anchored
        return ctx.exception

    def bundle(self, out):
        return Path(out["directory"])

    def writable(self, path):
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        return path


class TestHandoffExport(HandoffTestCase):
    def test_export_of_approved_version(self):
        out = self.export()
        directory = self.bundle(out)
        self.assertEqual(sorted(p.name for p in directory.iterdir()), sorted(hf.BUNDLE_FILES))
        source = self.builder.root / self.v2["package_id"]
        for name in hf.PACKAGE_FILES:  # byte-exact copies of the approved version
            self.assertEqual((directory / name).read_bytes(), (source / name).read_bytes())
            self.assertFalse(os.stat(directory / name).st_mode & 0o222, name)  # read-only
        body = out["handoff"]
        self.assertEqual(cxp.digest_id("handoff", body), out["handoff_id"])
        self.assertEqual((body["status"], body["scope"], body["publication_authorized"], body["generated_media_exists"]),
                         (hf.HANDED_OFF, "PRODUCTION_PREPARATION_ONLY", False, False))
        self.assertEqual(body["signoff"], {"signer": SIGNER, "signed_at": T_SIGN,
                                           "attests": "this exact package version is approved for production preparation"})
        self.assertEqual(body["approvals"]["package_review"]["reviewer"], REVIEWER)
        self.assertTrue(body["approvals"]["candidate_review"]["acceptance_is_not_verification"])
        self.assertEqual([(c["package_revision"], c["package_id"], c["editor"]) for c in body["revision_chain"]],
                         [(1, self.v1["package_id"], None), (2, self.v2["package_id"], EDITOR)])
        self.assertEqual(body["disclosure_summary"]["contradictions"], len(self.package["disclosures"]["contradictions"]))
        self.assertEqual(body["known_limitations"], list(hf.KNOWN_LIMITATIONS))
        record = self.x.get_record(out["handoff_record_id"])
        self.assertEqual((record.kind, record.provenance, record.evidence, record.verification),
                         (cxp.KIND_PRODUCTION_HANDOFF, cxp.HUMAN_ASSERTED, cxp.EV_NONE, cxp.VER_UNVERIFIED))
        self.assertEqual(sorted(record.derived_from), sorted([self.v2["package_record_id"],
                                                              body["approvals"]["package_review"]["review_id"]]))
        self.assertEqual(record.payload()["sums_sha256"], hf._sha((directory / "SHA256SUMS").read_bytes()))
        self.assertEqual(self.exporter.verify(out["handoff_id"]),
                         {"handoff_id": out["handoff_id"], "status": hf.HANDED_OFF, "intact": True, "current": True,
                          "integrity_problems": [], "currency_problems": [], "publication_authorized": False})

    def test_checksum_list_uses_the_sha256sum_format(self):
        directory = self.bundle(self.export())
        lines = (directory / "SHA256SUMS").read_text("ascii").splitlines()
        self.assertEqual([line.split("  ", 1)[1] for line in lines], sorted(set(hf.BUNDLE_FILES) - {"SHA256SUMS"}))
        for line in lines:  # "<64 hex>  <name>", text mode, as `sha256sum -c` expects
            digest, name = line.split("  ", 1)
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertEqual(digest, hf._sha((directory / name).read_bytes()))

    def test_first_version_can_be_handed_off_and_ids_are_deterministic(self):
        other = self.make(self.tmp / "b")
        # rebuild the identical history in a second, independent store
        from cognition import package_revision as rv
        artifact, _ = self.completed_cycle(other)
        studio = other[4]
        cid = studio.draft(artifact["artifact_id"], "2026-10-17T09:00:00Z")
        c = other[0].get_record(cid).payload()
        studio.review(cid, ep.APPROVED, "operator-founder", "2026-10-17T10:00:00Z",
                      accepted_uncertainties=c["contradiction_ids"] + c["unsupported_claims"])
        builder = pr.PackageBuilder(studio, self.tmp / "b" / "packages")
        builder.build(cid, "2026-10-17T11:00:00Z")
        editor = rv.PackageEditor(builder)
        v2 = editor.revise(self.v1["package_id"], EDITOR, self.presentation_edits(), T_EDIT)
        editor.review(v2["package_id"], ep.APPROVED, REVIEWER, T_REVIEW)
        twin = hf.HandoffExporter(editor, self.tmp / "b" / "handoffs").export(v2["package_id"], SIGNER, T_SIGN)
        out = self.export()
        self.assertEqual(twin["handoff_id"], out["handoff_id"])
        self.assertEqual(snapshot(self.tmp / "a" / "handoffs"), snapshot(self.tmp / "b" / "handoffs"))

    def test_unedited_first_version(self):
        fresh = self.make(self.tmp / "c")
        artifact, _ = self.completed_cycle(fresh)
        studio = fresh[4]
        cid = studio.draft(artifact["artifact_id"], "2026-10-17T09:00:00Z")
        c = fresh[0].get_record(cid).payload()
        studio.review(cid, ep.APPROVED, "operator-founder", "2026-10-17T10:00:00Z",
                      accepted_uncertainties=c["contradiction_ids"] + c["unsupported_claims"])
        from cognition import package_revision as rv
        editor = rv.PackageEditor(pr.PackageBuilder(studio, self.tmp / "c" / "packages"))
        v1 = editor.builder.build(cid, "2026-10-17T11:00:00Z")
        editor.review(v1["package_id"], ep.APPROVED, REVIEWER, T_REVIEW)
        out = hf.HandoffExporter(editor, self.tmp / "c" / "handoffs").export(v1["package_id"], REVIEWER, T_SIGN)
        self.assertEqual([c["editor"] for c in out["handoff"]["revision_chain"]], [None])


class TestHandoffRefusals(HandoffTestCase):
    def test_unreviewed_and_negatively_reviewed_versions(self):
        v3 = self.revise([{"op": "set_audio", "scene_id": self.scene[pr.DRAMATIZATION]["scene_id"],
                           "music": "silence", "pacing": "slow"}], self.v2["package_id"], at=T_EDIT2)
        self.refused(f"{hf.H_NOT_APPROVED}:DRAFT", v3["package_id"])
        self.editor.review(v3["package_id"], ep.APPROVED, REVIEWER, T_LATER)
        self.editor.review(v3["package_id"], ep.NEEDS_REVISION, "operator-editor", T_LATER)
        self.refused(f"{hf.H_NOT_APPROVED}:{ep.NEEDS_REVISION}", v3["package_id"])

    def test_superseded_version_cannot_be_handed_off(self):
        self.revise([{"op": "set_audio", "scene_id": self.scene[pr.DRAMATIZATION]["scene_id"],
                      "music": "silence", "pacing": "slow"}], self.v2["package_id"], at=T_EDIT2)
        self.refused(f"{hf.H_NOT_APPROVED}:SUPERSEDED")

    def test_withdrawn_candidate_approval(self):
        self.studio.review(self.candidate, ep.NEEDS_REVISION, "operator-editor", T_LATER)
        self.refused(pr.P_NOT_APPROVED)

    def test_signer_identity(self):
        self.refused(hf.H_SIGNER_IS_EDITOR, signer=EDITOR)
        for person in ("lens-muse", "coordinator", "Jane Producer", None, "package-builder"):
            with self.subTest(person):
                self.refused("UNAUTHORIZED_SIGNER", signer=person)
        with self.g.running():
            self.refused("SIGNER_DURING_RUNNING_CYCLE")

    def test_one_handoff_per_version(self):
        out = self.export()
        self.refused(f"{hf.H_EXISTS}:{out['handoff_id']}")

    def test_tampered_source_package(self):
        path = self.builder.root / self.v2["package_id"] / "package.md"
        path.write_bytes(path.read_bytes() + b"\nThis was proven in the lab.\n")
        self.refused(pr.P_TAMPERED)

    def test_unknown_package(self):
        self.refused(hf.H_UNKNOWN_PACKAGE, package_id="cxp-pkg-" + "0" * 64)


class TestHandoffVerification(HandoffTestCase):
    def test_tampering_is_detected(self):
        out = self.export()
        directory = self.bundle(out)
        original = {p.name: p.read_bytes() for p in directory.iterdir()}

        def restore():
            for p in directory.iterdir():
                if p.name not in original:
                    p.unlink()
            for name, data in original.items():
                path = directory / name
                if path.exists():
                    self.writable(path)
                path.write_bytes(data)

        cases = {
            "FILE_TAMPERED:package.md": lambda: self.writable(directory / "package.md").write_bytes(b"edited"),
            "FILE_MISSING:manifest.json": lambda: (directory / "manifest.json").unlink(),
            "UNEXPECTED_FILE:video.mp4": lambda: (directory / "video.mp4").write_bytes(b"x"),
            "CHECKSUM_LIST_NOT_ANCHORED": lambda: self.writable(directory / "SHA256SUMS").write_bytes(
                original["SHA256SUMS"] + b"0" * 64 + b"  extra\n"),
        }
        for problem, damage in cases.items():
            with self.subTest(problem):
                damage()
                result = self.exporter.verify(out["handoff_id"])
                self.assertEqual((result["status"], result["intact"]), (hf.INVALID, False))
                self.assertIn(problem, result["integrity_problems"])
                restore()
        # rewriting a file AND its checksum line is still caught by the CXP anchor
        edited = b"Replay is always refused. Verified."
        self.writable(directory / "package.md").write_bytes(edited)
        sums = {name: (directory / name).read_bytes() for name in hf.BUNDLE_FILES if name != "SHA256SUMS"}
        self.writable(directory / "SHA256SUMS").write_bytes(hf.render_sums(sums))
        problems = self.exporter.verify(out["handoff_id"])["integrity_problems"]
        self.assertIn("CHECKSUM_LIST_NOT_ANCHORED", problems)
        self.assertIn("ARTIFACT_LIST_MISMATCH", problems)
        restore()
        self.assertEqual(self.exporter.verify(out["handoff_id"])["status"], hf.HANDED_OFF)

    def test_approval_is_not_carried_forward(self):
        out = self.export()
        v3 = self.revise([{"op": "set_audio", "scene_id": self.scene[pr.DRAMATIZATION]["scene_id"],
                           "music": "silence", "pacing": "slow"}], self.v2["package_id"], at=T_EDIT2)
        result = self.exporter.verify(out["handoff_id"])
        self.assertEqual((result["status"], result["intact"], result["current"]), (hf.STALE, True, False))
        self.assertEqual(result["currency_problems"], [f"{hf.H_NOT_APPROVED}:SUPERSEDED"])
        self.refused(f"{hf.H_NOT_APPROVED}:DRAFT", v3["package_id"])  # the new version needs its own review

    def test_withdrawn_candidate_approval_makes_handoff_stale(self):
        out = self.export()
        self.studio.review(self.candidate, ep.NEEDS_REVISION, "operator-editor", T_LATER)
        result = self.exporter.verify(out["handoff_id"])
        self.assertEqual((result["status"], result["intact"]), (hf.STALE, True))

    def test_unanchored_bundle_and_crash_recovery(self):
        with mock.patch.object(self.x, "ingest", side_effect=RuntimeError("power loss")):
            with self.assertRaises(RuntimeError):
                self.export()
        orphan = [p for p in self.exporter.root.iterdir()]
        self.assertEqual(len(orphan), 1)
        result = self.exporter.verify(orphan[0].name)
        self.assertEqual(result["status"], hf.INVALID)
        self.assertIn("NOT_ANCHORED", result["integrity_problems"])
        out = self.export()  # the same export completes
        self.assertEqual(out["handoff_id"], orphan[0].name)
        self.assertEqual(self.exporter.verify(out["handoff_id"])["status"], hf.HANDED_OFF)

    def test_refused_ingest_leaves_no_bundle(self):
        rejected = mock.Mock(status="REJECTED", error_code=cxp.E_TRANSITION_REFUSED, detail="refused")
        with mock.patch.object(self.x, "ingest", return_value=rejected):
            with self.assertRaises(hf.HandoffRefused):
                self.export()
        self.assertEqual(list(self.exporter.root.iterdir()), [])


class TestHandoffRecordRules(HandoffTestCase):
    def forged(self, package=None, review_id=None, signer=SIGNER, **labels):
        package = package or self.v2
        review_id = review_id or self.editor.status(package["package_id"])["reviews"][0]["review_id"]
        event = {"schema_version": 1, "kind": cxp.KIND_PRODUCTION_HANDOFF, "representation": cxp.REP_PARAPHRASE,
                 "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.HUMAN_ASSERTED,
                 "privacy": cxp.PRIV_INTERNAL,
                 "payload": {"handoff_id": "cxp-hof-" + "1" * 64, "package_record_id": package["package_record_id"],
                             "package_id": package["package_id"], "package_review_id": review_id, "signer": signer,
                             "sums_sha256": "2" * 64, "publication_authorized": False},
                 "sources": [], "derived_from": sorted([package["package_record_id"], review_id]),
                 "verification_ref": None, "consent_ref": None,
                 "occurrence": {"emitter_id": signer, "observed_at": T_SIGN}}
        event.update(labels)
        return event

    def test_ingest_refuses_what_the_exporter_refuses(self):
        self.assertEqual(self.x.ingest(self.forged(signer=EDITOR)).error_code, cxp.E_TRANSITION_REFUSED)
        evidence = self.forged(provenance=cxp.UNVERIFIED_INTERPRETATION)
        self.assertEqual(self.x.ingest(evidence).error_code, cxp.E_KIND_RULE)
        published = self.forged()
        published["payload"]["publication_authorized"] = True
        self.assertEqual(self.x.ingest(published).error_code, cxp.E_KIND_RULE)
        # a review of another version cannot carry a handoff
        v1_review = self.editor.review(self.v1["package_id"], ep.NEEDS_REVISION, REVIEWER, T_LATER)
        self.assertEqual(self.x.ingest(self.forged(review_id=v1_review)).error_code, cxp.E_TRANSITION_REFUSED)
        # superseded version, even with its old approval
        self.assertEqual(self.x.ingest(self.forged(package=self.v1, review_id=v1_review)).error_code,
                         cxp.E_TRANSITION_REFUSED)
        out = self.export()
        self.assertEqual(self.x.ingest(self.forged()).error_code, cxp.E_TRANSITION_REFUSED)  # one per version
        self.assertEqual(self.exporter.verify(out["handoff_id"])["status"], hf.HANDED_OFF)

    def test_ingest_refuses_a_superseded_version_despite_its_approval(self):
        approval = self.editor.status(self.v2["package_id"])["reviews"][0]["review_id"]  # a genuine APPROVED review
        self.revise([{"op": "set_audio", "scene_id": self.scene[pr.DRAMATIZATION]["scene_id"],
                      "music": "silence", "pacing": "slow"}], self.v2["package_id"], at=T_EDIT2)
        receipt = self.x.ingest(self.forged(review_id=approval))
        self.assertEqual(receipt.error_code, cxp.E_TRANSITION_REFUSED)
        self.assertIn("superseded", receipt.detail)

    def test_handoffs_are_never_research_input(self):
        out = self.export()
        with self.assertRaises(co.CoordinatorError):
            co.LensCoordinator(self.x).run([out["handoff_record_id"]], "t", "2026-10-19T00:00:00Z")
        echo = self.accept(ev.claim([out["handoff_record_id"]], statement="It was signed off, so it is true.",
                                    evidence=cxp.EV_NONE))
        decision = self.runner.run([], "t", "2026-10-19T00:00:00Z", extra_input_ids=[echo])["governor_decision"]
        self.assertEqual(decision["reason_code"], gv.R_RECYCLED)

    def test_no_publication_surface(self):
        out = self.export()
        for target in (out["handoff"], self.x.get_record(out["handoff_record_id"]).payload(),
                       self.exporter.verify(out["handoff_id"])):
            self.assertIs(target["publication_authorized"], False)
        for obj in (hf.HandoffExporter, hf):
            for name in dir(obj):
                for word in ("publish", "upload", "schedule", "send", "post", "deliver", "invoice", "payment"):
                    self.assertNotIn(word, name.lower(), name)
        self.assertFalse(self.exporter.grants_execution_authority)
        source = Path(hf.__file__).read_text()
        for module in ("socket", "urllib", "http", "requests", "smtplib"):
            self.assertNotIn(f"import {module}", source)
