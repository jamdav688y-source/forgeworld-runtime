"""R2 Cognitive Lineage tests: ancestry reconstruction, independence,
repeated derivatives, epistemic class, integrity failures, erasure/privacy
redaction and determinism. Read-only queries over temporary stores."""
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition.tests import _events as ev
from cognition.tests.test_exchange import snapshot
from cognition import cxp, exchange, lineage


class LineageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-r2-lineage-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.x = exchange.CognitiveExchange(self.tmp / "store")

    def accept(self, raw, x=None):
        receipt = (x or self.x).ingest(raw)
        self.assertEqual(receipt.status, exchange.ACCEPTED, (receipt.error_code, receipt.detail))
        return receipt.record_id

    def trace(self, record_id, **kw):
        return lineage.trace(self.x.record_metadata, record_id, **kw)


class TestAncestry(LineageTestCase):
    def test_observation_is_its_own_root(self):
        obs = self.accept(ev.observation())
        t = self.trace(obs)
        self.assertEqual(t["epistemic_class"], lineage.DIRECT_OBSERVATION)
        self.assertEqual(t["observation_roots"], [obs])
        self.assertEqual(t["max_derivation_depth"], 0)
        self.assertEqual(t["sources"][0]["locator"], ev.synthetic.PHASE0_COMMIT)
        self.assertEqual(t["sources"][0]["independence_basis"], lineage.BASIS_DEFAULT)

    def test_paraphrase_chain_is_a_restatement_of_one_source(self):
        parent = obs = self.accept(ev.observation())
        for i in range(3):
            parent = self.accept(ev.claim([parent], statement=f"restated {i}", representation=cxp.REP_PARAPHRASE))
        t = self.trace(parent)
        self.assertEqual(t["epistemic_class"], lineage.RESTATEMENT)
        self.assertEqual((t["observation_roots"], t["max_derivation_depth"]), ([obs], 3))
        self.assertEqual((t["distinct_source_count"], t["independent_origin_count"]), (1, 1))
        self.assertEqual([n["depth"] for n in t["nodes"]], [0, 1, 2, 3])

    def test_any_inferential_step_makes_the_record_inferred(self):
        obs = self.accept(ev.observation())
        inferred = self.accept(ev.claim([obs], representation=cxp.REP_INFERENCE))
        restated = self.accept(ev.claim([inferred], representation=cxp.REP_QUOTATION, statement="quoted inference"))
        self.assertEqual(self.trace(restated)["epistemic_class"], lineage.INFERRED)
        interp = self.accept(ev.claim([obs], representation=cxp.REP_PARAPHRASE, statement="interp",
                                      provenance=cxp.UNVERIFIED_INTERPRETATION))
        self.assertEqual(self.trace(interp)["epistemic_class"], lineage.INFERRED)

    def test_independent_sources_are_preserved_separately(self):
        a = self.accept(ev.observation(statement="seen in A", sources=[ev.source("doc-a")]))
        b = self.accept(ev.observation(statement="seen in B", sources=[ev.source("doc-b")]))
        both = self.accept(ev.claim([a, b], representation=cxp.REP_PARAPHRASE))
        t = self.trace(both)
        self.assertEqual(t["observation_roots"], sorted([a, b]))
        self.assertEqual(sorted(s["locator"] for s in t["sources"]), ["doc-a", "doc-b"])
        self.assertEqual(t["independent_origin_count"], 2)

    def test_declared_shared_origin_is_reported_not_trusted(self):
        obs = self.accept(ev.observation(sources=[ev.source("mirror-1", independence_key="publisher-x"),
                                                  ev.source("mirror-2", independence_key="publisher-x")]))
        t = self.trace(obs)
        self.assertEqual({s["independence_basis"] for s in t["sources"]}, {lineage.BASIS_DECLARED})
        self.assertEqual((t["distinct_source_count"], t["independent_origin_count"]), (2, 1))

    def test_shared_origins_flags_repeated_derivatives(self):
        a = self.accept(ev.observation(statement="origin A", sources=[ev.source("doc-a")]))
        b = self.accept(ev.observation(statement="origin B", sources=[ev.source("doc-b")]))
        copies = [self.accept(ev.claim([a], statement=f"copy {i}", representation=cxp.REP_PARAPHRASE)) for i in range(3)]
        other = self.accept(ev.claim([b], statement="from B"))
        report = lineage.shared_origins(self.x.record_metadata, copies + [other])
        self.assertEqual(report["independent_origin_count"], 2)
        self.assertEqual(len(report["repeated_origins"]), 1)
        self.assertEqual(report["origins"][report["repeated_origins"][0]], sorted(copies))


class TestDeterminismAndReadOnly(LineageTestCase):
    def _build(self, x):
        a = self.accept(ev.observation(statement="A", sources=[ev.source("doc-a")]), x)
        b = self.accept(ev.observation(statement="B", sources=[ev.source("doc-b")]), x)
        return self.accept(ev.claim([a, b]), x)

    def test_same_store_contents_give_identical_traces(self):
        other = exchange.CognitiveExchange(self.tmp / "other")
        r1, r2 = self._build(self.x), self._build(other)
        self.assertEqual(r1, r2)
        self.assertEqual(self.trace(r1), lineage.trace(other.record_metadata, r2))
        self.assertEqual(self.trace(r1), self.trace(r1))

    def test_queries_never_write(self):
        rid = self._build(self.x)
        before = snapshot(self.tmp / "store")
        self.trace(rid)
        lineage.shared_origins(self.x.record_metadata, [rid])
        self.assertEqual(snapshot(self.tmp / "store"), before)


def fake(record_id, kind=cxp.KIND_CLAIM, parents=(), sources=(), **extra):
    meta = {"record_id": record_id, "kind": kind, "representation": cxp.REP_PARAPHRASE, "provenance": cxp.DERIVED,
            "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "privacy": cxp.PRIV_INTERNAL,
            "sources": list(sources), "root_sources": list(sources), "derived_from": list(parents), "erased": False}
    meta.update(extra)
    return meta


class TestIntegrityFailures(unittest.TestCase):
    def check(self, metas, query, code):
        table = {m["record_id"]: m for m in metas}
        with self.assertRaises(lineage.LineageError) as ctx:
            lineage.trace(table.get, query)
        self.assertEqual(ctx.exception.code, code)

    def test_cycle(self):
        self.check([fake("a", parents=["b"]), fake("b", parents=["a"])], "a", lineage.E_CYCLE)

    def test_self_reference(self):
        self.check([fake("a", parents=["a"])], "a", lineage.E_CYCLE)

    def test_dangling_and_unknown(self):
        self.check([fake("a", parents=["missing"])], "a", lineage.E_DANGLING_REFERENCE)
        self.check([], "nothing", lineage.E_UNKNOWN_RECORD)

    def test_malformed_metadata(self):
        broken = fake("a")
        del broken["privacy"]
        self.check([broken], "a", lineage.E_MALFORMED_METADATA)
        self.check([fake("a", parents=[])], "a", lineage.E_MALFORMED_METADATA)  # derived kind without parents
        self.check([fake("a", kind="UNKNOWN", parents=["b"])], "a", lineage.E_MALFORMED_METADATA)
        self.check([fake("a", parents=["b"]), fake("b", kind=cxp.KIND_OBSERVATION, parents=["c"])], "a",
                   lineage.E_MALFORMED_METADATA)

    def test_recorded_roots_must_match_reconstructed_lineage(self):
        src = {"source_id": "s1", "source_type": "document", "locator": "x", "independence_key": "s1"}
        obs = fake("o", kind=cxp.KIND_OBSERVATION, sources=[src])
        self.check([fake("a", parents=["o"], root_sources=[]), obs], "a", lineage.E_MALFORMED_METADATA)

    def test_depth_bound(self):
        src = {"source_id": "s1", "source_type": "document", "locator": "x", "independence_key": "s1"}
        n = lineage.MAX_DEPTH + 2
        metas = [fake(f"n{i}", parents=[f"n{i + 1}"], root_sources=[src]) for i in range(n)]
        metas.append(fake(f"n{n}", kind=cxp.KIND_OBSERVATION, sources=[src]))
        self.check(metas, "n0", lineage.E_DEPTH_EXCEEDED)


class TestErasureAndPrivacy(LineageTestCase):
    def test_erased_roots_are_redacted_but_structure_survives(self):
        obs = self.accept(ev.observation(sources=[ev.source("private-ish-doc", independence_key="publisher-y")]))
        child = self.accept(ev.claim([obs]))
        self.x.erase(obs, "synthetic-erasure")
        t = self.trace(child)
        root = next(n for n in t["nodes"] if n["record_id"] == obs)
        self.assertTrue(root["erased"] and root["redacted"])
        self.assertEqual(t["observation_roots"], [obs])
        source = t["sources"][0]
        self.assertIsNone(source["locator"])
        self.assertTrue(source["redacted"])
        self.assertTrue(source["origin"].startswith("redacted-origin-"))
        self.assertNotIn("publisher-y", repr(t))

    def test_clearance_below_record_privacy_redacts(self):
        obs = self.accept(ev.observation(privacy=cxp.PRIV_INTERNAL))
        t = self.trace(obs, clearance=cxp.PRIV_PUBLIC)
        self.assertTrue(t["nodes"][0]["redacted"])
        self.assertIsNone(t["sources"][0]["locator"])
        self.assertIsNotNone(self.trace(obs)["sources"][0]["locator"])

    def test_invalid_clearance(self):
        obs = self.accept(ev.observation())
        with self.assertRaises(ValueError):
            self.trace(obs, clearance="TOP_SECRET")


if __name__ == "__main__":
    unittest.main()
