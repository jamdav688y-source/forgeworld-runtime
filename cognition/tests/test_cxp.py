"""CXP v1 schema, canonical serialization, identity and authority tests
(structural; no lineage lookup, no persistence)."""
import ast
import copy
import unittest
from pathlib import Path

from cognition.tests import _events as ev
from cognition import cxp, exchange

COGNITION_DIR = Path(__file__).resolve().parent.parent


def rejects(test, raw, code):
    with test.assertRaises(cxp.CXPError) as ctx:
        cxp.parse_event(raw)
    test.assertEqual(ctx.exception.code, code, ctx.exception.detail)


class TestValidEvent(unittest.TestCase):
    def test_phase0_observation_parses_with_all_dimensions_preserved(self):
        record, occurrence = cxp.parse_event(ev.observation())
        self.assertEqual(record.kind, cxp.KIND_OBSERVATION)
        self.assertEqual((record.representation, record.evidence, record.verification),
                         (cxp.REP_QUOTATION, cxp.EV_SINGLE_SOURCE, cxp.VER_UNVERIFIED))
        self.assertEqual(record.provenance, cxp.OBSERVED)
        self.assertEqual(record.sources[0].source_type, "git_commit")
        self.assertEqual(occurrence.record_id, record.record_id)
        self.assertEqual(occurrence.correlation_id, "cycle-r1-demo")

    def test_payload_is_a_fresh_copy_each_time(self):
        record, _ = cxp.parse_event(ev.observation())
        first = record.payload()
        first["statement"] = "tampered"
        self.assertNotEqual(record.payload()["statement"], "tampered")


class TestInvalidEventRejection(unittest.TestCase):
    def test_non_object(self):
        rejects(self, ["not", "an", "event"], cxp.E_MALFORMED)

    def test_unknown_top_level_key(self):
        rejects(self, ev.observation(extra_field=1), cxp.E_MALFORMED)

    def test_missing_required_key(self):
        raw = ev.observation()
        del raw["provenance"]
        rejects(self, raw, cxp.E_MALFORMED)

    def test_unknown_enum_values(self):
        for key in ("representation", "evidence", "verification", "provenance", "privacy"):
            with self.subTest(key=key):
                rejects(self, ev.observation(**{key: "MADE_UP"}), cxp.E_MALFORMED)

    def test_empty_statement(self):
        rejects(self, ev.observation(statement="   "), cxp.E_MALFORMED)

    def test_float_in_payload(self):
        raw = ev.observation()
        raw["payload"]["subject"] = 1.5
        rejects(self, raw, cxp.E_MALFORMED)

    def test_bad_timestamp(self):
        rejects(self, ev.with_occurrence(ev.observation(), observed_at="yesterday"), cxp.E_MALFORMED)

    def test_bad_emitter_id(self):
        rejects(self, ev.with_occurrence(ev.observation(), emitter_id="../etc"), cxp.E_MALFORMED)

    def test_oversized_payload(self):
        raw = ev.observation()
        raw["payload"]["subject"] = "x" * (cxp.MAX_PAYLOAD_BYTES + 1)
        rejects(self, raw, cxp.E_PAYLOAD_TOO_LARGE)

    def test_reserved_kind_is_not_enabled(self):
        rejects(self, ev.observation(kind="EPISODE_CANDIDATE"), cxp.E_KIND_NOT_ENABLED)

    def test_observation_cannot_derive(self):
        rejects(self, ev.observation(derived_from=["cxp-rec-" + "0" * 64]), cxp.E_KIND_RULE)

    def test_observation_cannot_be_an_inference(self):
        rejects(self, ev.observation(representation=cxp.REP_INFERENCE), cxp.E_KIND_RULE)

    def test_claim_cannot_cite_its_own_sources(self):
        rejects(self, ev.claim(["cxp-rec-" + "0" * 64], sources=[ev.source("x")]), cxp.E_KIND_RULE)

    def test_duplicate_source(self):
        rejects(self, ev.observation(sources=[ev.source("a"), ev.source("a")]), cxp.E_MALFORMED)


class TestSchemaVersion(unittest.TestCase):
    def test_unsupported_version(self):
        rejects(self, ev.observation(schema_version=2), cxp.E_VERSION_UNSUPPORTED)
        rejects(self, ev.observation(schema_version=0), cxp.E_VERSION_UNSUPPORTED)

    def test_unsupported_version_is_reported_before_shape_errors(self):
        raw = {"schema_version": 2, "some_future_field": True}
        rejects(self, raw, cxp.E_VERSION_UNSUPPORTED)

    def test_non_integer_versions_are_malformed(self):
        for bad in ("1", True, 1.0, None):
            with self.subTest(bad=bad):
                rejects(self, ev.observation(schema_version=bad), cxp.E_MALFORMED)

    def test_missing_version_is_malformed(self):
        raw = ev.observation()
        del raw["schema_version"]
        rejects(self, raw, cxp.E_MALFORMED)


class TestCanonicalSerialization(unittest.TestCase):
    def test_key_order_does_not_matter(self):
        self.assertEqual(cxp.canonical_bytes({"b": 1, "a": [True, None, "é"]}),
                         cxp.canonical_bytes({"a": [True, None, "é"], "b": 1}))

    def test_exact_bytes(self):
        self.assertEqual(cxp.canonical_bytes({"b": 1, "a": "é"}), '{"a":"é","b":1}'.encode("utf-8"))

    def test_rejects_non_json_values(self):
        for bad in ({1: "int key"}, {"f": 0.1}, {"n": float("nan")}, {"s": {1, 2}}, {"b": b"bytes"}):
            with self.subTest(bad=bad), self.assertRaises(cxp.CXPError):
                cxp.canonical_bytes(bad)

    def test_digest_domains_are_separated(self):
        obj = {"same": "object"}
        self.assertNotEqual(cxp.digest_id("content", obj)[-64:], cxp.digest_id("record", obj)[-64:])


class TestIdentity(unittest.TestCase):
    def test_identity_is_stable_across_parses(self):
        a, occ_a = cxp.parse_event(ev.observation())
        b, occ_b = cxp.parse_event(copy.deepcopy(ev.observation()))
        self.assertEqual((a.content_id, a.record_id, occ_a.occurrence_id), (b.content_id, b.record_id, occ_b.occurrence_id))

    def test_one_byte_change_changes_content_and_record_identity(self):
        a, _ = cxp.parse_event(ev.observation(statement="grant held by receiver"))
        b, _ = cxp.parse_event(ev.observation(statement="grant held by receiver."))
        self.assertNotEqual(a.content_id, b.content_id)
        self.assertNotEqual(a.record_id, b.record_id)

    def test_occurrence_fields_never_enter_record_identity(self):
        a, occ_a = cxp.parse_event(ev.observation())
        b, occ_b = cxp.parse_event(ev.with_occurrence(ev.observation(), observed_at="2030-01-01T00:00:00Z",
                                                      emitter_id="other-emitter", correlation_id="c2",
                                                      causation_id="cause"))
        self.assertEqual(a.record_id, b.record_id)
        self.assertNotEqual(occ_a.occurrence_id, occ_b.occurrence_id)

    def test_correlation_and_causation_do_not_change_occurrence_identity(self):
        _, occ_a = cxp.parse_event(ev.observation())
        _, occ_b = cxp.parse_event(ev.with_occurrence(ev.observation(), correlation_id="c2", causation_id="x"))
        self.assertEqual(occ_a.occurrence_id, occ_b.occurrence_id)

    def test_distinct_occurrences_per_emitter_and_time(self):
        ids = {cxp.parse_event(ev.with_occurrence(ev.observation(), emitter_id=e, observed_at=t))[1].occurrence_id
               for e in ("emitter-a", "emitter-b") for t in ("2026-10-17T00:00:00Z", "2026-10-17T00:00:01Z")}
        self.assertEqual(len(ids), 4)

    def test_same_statement_from_distinct_sources_is_not_collapsed(self):
        a, _ = cxp.parse_event(ev.observation(sources=[ev.source("doc-a")]))
        b, _ = cxp.parse_event(ev.observation(sources=[ev.source("doc-b")]))
        self.assertEqual(a.content_id, b.content_id)
        self.assertNotEqual(a.record_id, b.record_id)
        self.assertNotEqual(a.sources[0].source_id, b.sources[0].source_id)

    def test_epistemic_labels_are_part_of_record_identity(self):
        a, _ = cxp.parse_event(ev.observation())
        b, _ = cxp.parse_event(ev.observation(verification=cxp.VER_CONTESTED))
        self.assertEqual(a.content_id, b.content_id)
        self.assertNotEqual(a.record_id, b.record_id)

    def test_source_order_does_not_matter(self):
        a, _ = cxp.parse_event(ev.observation(sources=[ev.source("x"), ev.source("y")]))
        b, _ = cxp.parse_event(ev.observation(sources=[ev.source("y"), ev.source("x")]))
        self.assertEqual(a.record_id, b.record_id)


class TestVerificationAndPrivacyStructure(unittest.TestCase):
    def test_verified_requires_a_reference(self):
        rejects(self, ev.observation(verification=cxp.VER_VERIFIED), cxp.E_VERIFICATION_UNSUPPORTED)
        rejects(self, ev.observation(verification=cxp.VER_REFUTED), cxp.E_VERIFICATION_UNSUPPORTED)

    def test_dramatization_can_never_be_verified(self):
        raw = ev.claim(["cxp-rec-" + "1" * 64], representation=cxp.REP_DRAMATIZATION,
                       verification=cxp.VER_VERIFIED, verification_ref="cxp-rec-" + "2" * 64)
        rejects(self, raw, cxp.E_VERIFICATION_UNSUPPORTED)

    def test_verification_result_cannot_verify_itself(self):
        rejects(self, ev.verification_result("cxp-content-" + "0" * 64, verification=cxp.VER_VERIFIED,
                                             verification_ref="cxp-rec-" + "0" * 64), cxp.E_KIND_RULE)

    def test_verification_ref_without_a_verified_state_is_refused(self):
        rejects(self, ev.observation(verification_ref="cxp-rec-" + "0" * 64), cxp.E_KIND_RULE)

    def test_personal_requires_consent(self):
        rejects(self, ev.observation(privacy=cxp.PRIV_PERSONAL), cxp.E_PRIVACY_CONSENT_REQUIRED)
        cxp.parse_event(ev.observation(privacy=cxp.PRIV_PERSONAL, consent_ref="consent-synthetic-1"))


class TestNoExecutionAuthority(unittest.TestCase):
    def test_authority_shaped_payload_keys_are_refused_at_any_depth(self):
        for key in ("granted_capability_ids", "Authority_Context", "grant_id", "authkey", "token"):
            with self.subTest(key=key):
                rejects(self, ev.observation(payload={"statement": "x", key: ["content_read"]}),
                        cxp.E_AUTHORITY_FIELD_FORBIDDEN)
                rejects(self, ev.observation(payload={"statement": "x", "subject": "s",
                                                      "nested": [{"deeper": {key: True}}]}),
                        cxp.E_AUTHORITY_FIELD_FORBIDDEN)

    def test_records_and_receipts_never_grant_authority(self):
        record, _ = cxp.parse_event(ev.observation())
        self.assertFalse(record.grants_execution_authority)
        self.assertFalse(exchange.IngestReceipt(status=exchange.ACCEPTED).grants_execution_authority)

    def test_no_authority_bearing_methods(self):
        for cls in (cxp.CognitiveRecord, cxp.Occurrence, exchange.CognitiveExchange, exchange.IngestReceipt):
            names = [n for n in dir(cls) if not n.startswith("__")]
            for name in names:
                for word in ("execute", "authorize", "grant_", "issue", "permit"):
                    self.assertNotIn(word, name.lower(), f"{cls.__name__}.{name}")

    def test_cognition_package_imports_no_execution_or_network_modules(self):
        forbidden = {"fabric", "substrate", "subprocess", "socket", "http", "urllib", "requests",
                     "multiprocessing", "ssl", "asyncio"}
        for path in sorted(COGNITION_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    roots = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    roots = {node.module.split(".")[0]}
                else:
                    continue
                self.assertFalse(roots & forbidden, f"{path.relative_to(COGNITION_DIR)} imports {roots & forbidden}")


if __name__ == "__main__":
    unittest.main()
