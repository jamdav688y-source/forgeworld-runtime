"""Cognitive Exchange processing-contract tests: lineage, the R1 demonstration
flow, consumer independence and failure isolation, idempotency,
deterministic replay, erasure, integrity and clean rollback. All local and
in-process: temporary directories only, no sockets, no subprocesses."""
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cognition.tests import _events as ev
from cognition import cxp, exchange, synthetic
from evidence_envelope import envelope


class CountingConsumer:
    def __init__(self, consumer_id):
        self.consumer_id = consumer_id
        self.calls = []

    def consume(self, record):
        self.calls.append(record.record_id)
        return {"seen": record.record_id}


class FlakyConsumer:
    consumer_id = "synthetic-flaky"

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def consume(self, record):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("synthetic failure carrying payload text that must not be logged")
        return {"ok": True}


class MutatingConsumer:
    consumer_id = "synthetic-mutator"

    def consume(self, record):
        payload = record.payload()
        payload["statement"] = "MUTATED"
        return {"mutated": True}


class FixedOutputConsumer:
    def __init__(self, consumer_id, output):
        self.consumer_id = consumer_id
        self.output = output

    def consume(self, record):
        return self.output


def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and p.name != "exchange.lock"}


class ExchangeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-r1-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def make(self, *consumers, name="store"):
        return exchange.CognitiveExchange(self.tmp / name, consumers=consumers)

    def accept(self, x, raw):
        receipt = x.ingest(raw)
        self.assertEqual(receipt.status, exchange.ACCEPTED, (receipt.error_code, receipt.detail))
        return receipt


class TestR1Demonstration(ExchangeTestCase):
    """The ten-step R1 processing contract, end to end."""

    def test_one_observation_two_independent_consumers_replay_safe_no_authority(self):
        audit, terms = synthetic.SourceAuditConsumer(), synthetic.GovernanceTermConsumer()
        x = self.make(audit, terms)
        raw = synthetic.phase0_observation_event()

        # 1-5: ingest, validate, preserve provenance, deliver to two consumers, record results
        first = x.ingest(raw)
        self.assertEqual(first.status, exchange.ACCEPTED)
        self.assertEqual([r.status for r in first.consumer_results], [exchange.CONSUMED, exchange.CONSUMED])
        stored = x.get_record(first.record_id)
        self.assertEqual(stored.provenance, cxp.OBSERVED)
        self.assertEqual(stored.sources[0].locator, synthetic.PHASE0_COMMIT)
        self.assertEqual(x.record_metadata(first.record_id)["root_sources"][0]["locator"], synthetic.PHASE0_COMMIT)
        self.assertEqual(x.consumer_output("synthetic-source-audit", first.record_id)["source_types"], ["git_commit"])
        self.assertEqual(x.consumer_output("synthetic-governance-terms", first.record_id)["terms"],
                         ["authorize", "governed", "grants", "receiver-held"])

        # 6-7: reprocess -> idempotent
        ledger_before = (self.tmp / "store" / "exchange.jsonl").read_bytes()
        replay = x.ingest(raw)
        self.assertEqual(replay.status, exchange.DUPLICATE_OCCURRENCE)
        self.assertEqual({r.status for r in replay.consumer_results}, {exchange.ALREADY_CONSUMED})
        self.assertEqual([r.result_id for r in replay.consumer_results], [r.result_id for r in first.consumer_results])
        self.assertEqual((self.tmp / "store" / "exchange.jsonl").read_bytes(), ledger_before)

        # 8-9: malformed and unsupported-version events are rejected
        malformed = x.ingest({"kind": "OBSERVATION"})
        self.assertEqual((malformed.status, malformed.error_code), (exchange.REJECTED, cxp.E_MALFORMED))
        future = x.ingest(dict(raw, schema_version=2))
        self.assertEqual((future.status, future.error_code), (exchange.REJECTED, cxp.E_VERSION_UNSUPPORTED))

        # 10: nothing here grants execution authority
        for receipt in (first, replay, malformed, future):
            self.assertFalse(receipt.grants_execution_authority)
        self.assertFalse(stored.grants_execution_authority)


class TestIdempotency(ExchangeTestCase):
    def test_new_sighting_of_known_record_is_recorded_but_not_reprocessed(self):
        a, b = CountingConsumer("consumer-a"), CountingConsumer("consumer-b")
        x = self.make(a, b)
        first = self.accept(x, ev.observation())
        later = x.ingest(ev.with_occurrence(ev.observation(), observed_at="2026-10-18T00:00:00Z"))
        self.assertEqual(later.status, exchange.DUPLICATE_RECORD)
        self.assertEqual(later.record_id, first.record_id)
        self.assertNotEqual(later.occurrence_id, first.occurrence_id)
        self.assertEqual((len(a.calls), len(b.calls)), (1, 1))
        occurrences = [e for e in x.ledger_entries() if e["entry"] == "OCCURRENCE"]
        self.assertEqual(len(occurrences), 2)

    def test_reopened_exchange_does_not_reprocess(self):
        a = CountingConsumer("consumer-a")
        self.accept(self.make(a), ev.observation())
        again = CountingConsumer("consumer-a")
        receipt = self.make(again).ingest(ev.observation())
        self.assertEqual(receipt.status, exchange.DUPLICATE_OCCURRENCE)
        self.assertEqual(again.calls, [])

    def test_new_consumer_catches_up_on_redelivery_without_rerunning_old_ones(self):
        a = CountingConsumer("consumer-a")
        self.accept(self.make(a), ev.observation())
        a2, b = CountingConsumer("consumer-a"), CountingConsumer("consumer-b")
        self.make(a2, b).ingest(ev.observation())
        self.assertEqual((len(a2.calls), len(b.calls)), (0, 1))


class TestConsumerIndependenceAndFailureIsolation(ExchangeTestCase):
    def test_consumer_failure_is_isolated_and_retried_only_for_that_consumer(self):
        flaky, steady = FlakyConsumer(fail_times=1), CountingConsumer("consumer-steady")
        x = self.make(flaky, steady)
        first = x.ingest(ev.observation())
        self.assertEqual([r.status for r in first.consumer_results], [exchange.FAILED, exchange.CONSUMED])
        self.assertEqual(first.consumer_results[0].error_type, "RuntimeError")
        self.assertNotIn(b"payload text", (self.tmp / "store" / "exchange.jsonl").read_bytes())
        second = x.ingest(ev.observation())
        self.assertEqual([r.status for r in second.consumer_results], [exchange.CONSUMED, exchange.ALREADY_CONSUMED])
        self.assertEqual((flaky.calls, len(steady.calls)), (2, 1))

    def test_a_consumer_cannot_alter_what_another_consumer_sees(self):
        seen = []

        class Reader:
            consumer_id = "synthetic-reader"

            def consume(self, record):
                seen.append(record.payload()["statement"])
                return {}

        x = self.make(MutatingConsumer(), Reader())
        self.accept(x, ev.observation(statement="original"))
        self.assertEqual(seen, ["original"])

    def test_invalid_consumer_outputs_are_recorded_as_failures(self):
        cases = {
            "out-not-dict": ["list"],
            "out-float": {"score": 0.5},
            "out-authority": {"granted_capability_ids": ["content_read"]},
        }
        consumers = [FixedOutputConsumer(cid, out) for cid, out in cases.items()]
        good = CountingConsumer("consumer-good")
        receipt = self.make(*consumers, good).ingest(ev.observation())
        statuses = {r.consumer_id: (r.status, r.error_type) for r in receipt.consumer_results}
        self.assertEqual(statuses["out-not-dict"], (exchange.FAILED, "CXPError:SCHEMA_MALFORMED"))
        self.assertEqual(statuses["out-float"], (exchange.FAILED, "CXPError:SCHEMA_MALFORMED"))
        self.assertEqual(statuses["out-authority"], (exchange.FAILED, "CXPError:AUTHORITY_FIELD_FORBIDDEN"))
        self.assertEqual(statuses["consumer-good"][0], exchange.CONSUMED)

    def test_duplicate_or_invalid_consumer_ids_are_refused(self):
        with self.assertRaises(ValueError):
            self.make(CountingConsumer("same"), CountingConsumer("same"))
        with self.assertRaises(cxp.CXPError):
            self.make(CountingConsumer("../escape"))


class TestLineageAndEvidence(ExchangeTestCase):
    def test_derivation_chain_from_one_source_stays_single_source(self):
        x = self.make()
        parent = self.accept(x, ev.observation()).record_id
        for i in range(3):
            parent = self.accept(x, ev.claim([parent], statement=f"paraphrase {i}",
                                             representation=cxp.REP_PARAPHRASE)).record_id
        self.assertEqual(len(x.record_metadata(parent)["root_sources"]), 1)
        inflated = x.ingest(ev.claim([parent], evidence=cxp.EV_INDEPENDENT_SOURCES))
        self.assertEqual(inflated.error_code, cxp.E_EVIDENCE_INFLATION)

    def test_two_claims_sharing_one_root_are_not_independent(self):
        x = self.make()
        root = self.accept(x, ev.observation()).record_id
        c1 = self.accept(x, ev.claim([root], statement="reading one")).record_id
        c2 = self.accept(x, ev.claim([root], statement="reading two")).record_id
        combined = x.ingest(ev.claim([c1, c2], statement="both readings", evidence=cxp.EV_INDEPENDENT_SOURCES))
        self.assertEqual(combined.error_code, cxp.E_EVIDENCE_INFLATION)
        self.assertEqual(len(x.record_metadata(self.accept(x, ev.claim([c1, c2])).record_id)["root_sources"]), 1)

    def test_independent_sources_need_distinct_independence_keys(self):
        x = self.make()
        same_origin = x.ingest(ev.observation(evidence=cxp.EV_INDEPENDENT_SOURCES, sources=[
            ev.source("mirror-a", independence_key="publisher-1"), ev.source("mirror-b", independence_key="publisher-1")]))
        self.assertEqual(same_origin.error_code, cxp.E_EVIDENCE_INFLATION)
        self.accept(x, ev.observation(evidence=cxp.EV_INDEPENDENT_SOURCES, sources=[
            ev.source("report-a", independence_key="publisher-1"), ev.source("report-b", independence_key="publisher-2")]))

    def test_single_source_cannot_claim_more(self):
        x = self.make()
        for evidence in (cxp.EV_INDEPENDENT_SOURCES, cxp.EV_EXPERIMENT_REFERENCE):
            with self.subTest(evidence=evidence):
                self.assertEqual(x.ingest(ev.observation(evidence=evidence)).error_code, cxp.E_EVIDENCE_INFLATION)
        self.accept(x, ev.observation(evidence=cxp.EV_EXPERIMENT_REFERENCE,
                                      sources=[ev.source("exp-001", source_type="experiment")]))

    def test_transformation_cannot_raise_evidence_above_parent(self):
        x = self.make()
        weak = self.accept(x, ev.observation(evidence=cxp.EV_NONE)).record_id
        self.assertEqual(x.ingest(ev.claim([weak], evidence=cxp.EV_SINGLE_SOURCE)).error_code, cxp.E_EVIDENCE_INFLATION)
        self.accept(x, ev.claim([weak], evidence=cxp.EV_NONE))

    def test_unresolved_parent_is_rejected(self):
        receipt = self.make().ingest(ev.claim(["cxp-rec-" + "a" * 64]))
        self.assertEqual(receipt.error_code, cxp.E_LINEAGE_UNRESOLVED)

    def test_privacy_cannot_be_laundered_through_derivation(self):
        x = self.make()
        internal = self.accept(x, ev.observation(privacy=cxp.PRIV_INTERNAL)).record_id
        self.assertEqual(x.ingest(ev.claim([internal], privacy=cxp.PRIV_PUBLIC)).error_code, cxp.E_PRIVACY_DOWNGRADE)


class TestVerification(ExchangeTestCase):
    def test_verification_requires_a_matching_accepted_result(self):
        x = self.make()
        obs = self.accept(x, ev.observation())
        content_id = x.get_record(obs.record_id).content_id
        dangling = x.ingest(ev.observation(verification=cxp.VER_VERIFIED, verification_ref="cxp-rec-" + "b" * 64))
        self.assertEqual(dangling.error_code, cxp.E_VERIFICATION_UNSUPPORTED)

        other = self.accept(x, ev.verification_result("cxp-content-" + "c" * 64)).record_id
        wrong_target = x.ingest(ev.observation(verification=cxp.VER_VERIFIED, verification_ref=other))
        self.assertEqual(wrong_target.error_code, cxp.E_VERIFICATION_UNSUPPORTED)

        refuted = self.accept(x, ev.verification_result(content_id, outcome=cxp.VER_REFUTED)).record_id
        wrong_outcome = x.ingest(ev.observation(verification=cxp.VER_VERIFIED, verification_ref=refuted))
        self.assertEqual(wrong_outcome.error_code, cxp.E_VERIFICATION_UNSUPPORTED)

        not_a_result = x.ingest(ev.observation(verification=cxp.VER_VERIFIED, verification_ref=obs.record_id))
        self.assertEqual(not_a_result.error_code, cxp.E_VERIFICATION_UNSUPPORTED)

        good = self.accept(x, ev.verification_result(content_id)).record_id
        verified = self.accept(x, ev.observation(verification=cxp.VER_VERIFIED, verification_ref=good))
        self.assertNotEqual(verified.record_id, obs.record_id)  # a verified assertion is a distinct record

    def test_verification_is_not_inherited_by_derivations(self):
        x = self.make()
        obs = self.accept(x, ev.observation()).record_id
        vr = self.accept(x, ev.verification_result(x.get_record(obs).content_id)).record_id
        verified = self.accept(x, ev.observation(verification=cxp.VER_VERIFIED, verification_ref=vr)).record_id
        child = x.ingest(ev.claim([verified], verification=cxp.VER_VERIFIED, verification_ref=vr))
        self.assertEqual(child.error_code, cxp.E_VERIFICATION_UNSUPPORTED)
        self.assertEqual(x.get_record(self.accept(x, ev.claim([verified])).record_id).verification, cxp.VER_UNVERIFIED)


class TestDeterministicReplay(ExchangeTestCase):
    def _sequence(self):
        events = [synthetic.phase0_observation_event()]
        root, _ = cxp.parse_event(events[0])
        events.append(ev.claim([root.record_id]))
        events.append(ev.with_occurrence(events[0], observed_at="2026-10-18T00:00:00Z"))
        events.append(events[0])
        events.append({"broken": True})
        return events

    def test_same_events_produce_byte_identical_ledgers_and_outputs(self):
        stores = []
        for name in ("run-1", "run-2"):
            x = self.make(synthetic.SourceAuditConsumer(), synthetic.GovernanceTermConsumer(), name=name)
            statuses = [x.ingest(e).status for e in self._sequence()]
            stores.append((x, statuses))
        (x1, s1), (x2, s2) = stores
        self.assertEqual(s1, s2)
        self.assertEqual(s1, [exchange.ACCEPTED, exchange.ACCEPTED, exchange.DUPLICATE_RECORD,
                              exchange.DUPLICATE_OCCURRENCE, exchange.REJECTED])
        self.assertEqual(x1.state_digest(), x2.state_digest())
        self.assertEqual(snapshot(self.tmp / "run-1"), snapshot(self.tmp / "run-2"))

    def test_full_replay_into_same_store_changes_nothing(self):
        x = self.make(synthetic.SourceAuditConsumer(), synthetic.GovernanceTermConsumer())
        for e in self._sequence():
            x.ingest(e)
        before = snapshot(self.tmp / "store")
        for e in self._sequence():
            x.ingest(e)
        self.assertEqual(snapshot(self.tmp / "store"), before)


class TestCleanRollbackAndIntegrity(ExchangeTestCase):
    def test_rejected_events_leave_the_store_untouched(self):
        x = self.make(CountingConsumer("consumer-a"))
        self.accept(x, ev.observation())
        before = snapshot(self.tmp / "store")
        for bad in ({"schema_version": 1}, dict(ev.observation(), schema_version=9),
                    ev.claim(["cxp-rec-" + "d" * 64]), ev.observation(evidence=cxp.EV_INDEPENDENT_SOURCES),
                    ev.observation(privacy=cxp.PRIV_PERSONAL, consent_ref="consent-synthetic-1"),
                    ev.observation(payload={"statement": "x", "grant": "all"})):
            self.assertEqual(x.ingest(bad).status, exchange.REJECTED)
        self.assertEqual(snapshot(self.tmp / "store"), before)

    def test_failed_commit_leaves_no_partial_record(self):
        x = self.make(CountingConsumer("consumer-a"))
        self.accept(x, ev.observation(statement="first"))
        before = snapshot(self.tmp / "store")
        real_write = envelope._atomic_write_bytes

        def failing_write(path, data):
            if path.name == "exchange.jsonl":
                raise OSError("synthetic disk failure")
            return real_write(path, data)

        with mock.patch.object(envelope, "_atomic_write_bytes", failing_write):
            with self.assertRaises(OSError):
                x.ingest(ev.observation(statement="second"))
        self.assertEqual(snapshot(self.tmp / "store"), before)
        retry = self.accept(x, ev.observation(statement="second"))
        self.assertEqual(retry.consumer_results[0].status, exchange.CONSUMED)

    def test_corrupt_ledger_fails_closed(self):
        x = self.make()
        self.accept(x, ev.observation())
        ledger = self.tmp / "store" / "exchange.jsonl"
        ledger.write_bytes(ledger.read_bytes().replace(b'"evidence": "SINGLE_SOURCE"', b'"evidence": "INDEPENDENT_SOURCES"'))
        with self.assertRaises(envelope.LedgerIntegrityError):
            x.ingest(ev.observation(statement="another"))
        ledger.write_bytes(b'{"entry": "RECORD"')
        with self.assertRaises(envelope.LedgerIntegrityError):
            x.state_digest()

    def test_tampered_payload_fails_closed(self):
        x = self.make()
        rid = self.accept(x, ev.observation()).record_id
        (self.tmp / "store" / "payloads" / f"{rid}.json").write_text('{"statement":"rewritten history"}')
        with self.assertRaises(envelope.LedgerIntegrityError):
            x.get_record(rid)


class TestErasureAndPrivacy(ExchangeTestCase):
    def test_erasure_removes_content_keeps_lineage_and_blocks_reuse(self):
        x = self.make(synthetic.GovernanceTermConsumer())
        statement = "Synthetic erasable statement about grants"
        obs = self.accept(x, ev.observation(statement=statement)).record_id
        child = self.accept(x, ev.claim([obs])).record_id
        x.erase(obs, "synthetic-erasure-request")

        self.assertIsNone(x.get_record(obs))
        self.assertIsNone(x.consumer_output("synthetic-governance-terms", obs))
        self.assertFalse((self.tmp / "store" / "payloads" / f"{obs}.json").exists())
        self.assertEqual(len(list((self.tmp / "store" / "outputs").iterdir())), 1)  # only the child's output remains
        self.assertNotIn(statement.encode(), (self.tmp / "store" / "exchange.jsonl").read_bytes())
        self.assertTrue(x.record_metadata(obs)["erased"])
        self.assertEqual(x.record_metadata(child)["derived_from"], [obs])

        self.assertEqual(x.ingest(ev.observation(statement=statement)).error_code, cxp.E_ERASED)
        self.assertEqual(x.ingest(ev.claim([obs], statement="new derivation")).error_code, cxp.E_ERASED)

    def test_personal_and_restricted_are_not_persisted_in_r1(self):
        x = self.make()
        for privacy in (cxp.PRIV_PERSONAL, cxp.PRIV_RESTRICTED):
            with self.subTest(privacy=privacy):
                receipt = x.ingest(ev.observation(privacy=privacy, consent_ref="consent-synthetic-1"))
                self.assertEqual(receipt.error_code, cxp.E_PRIVACY_PERSISTENCE_UNSUPPORTED)
        self.assertFalse((self.tmp / "store" / "exchange.jsonl").exists())


class TestNoSideEffectsOutsideTheStore(ExchangeTestCase):
    def test_exchange_writes_only_inside_its_own_root(self):
        x = self.make(synthetic.SourceAuditConsumer(), synthetic.GovernanceTermConsumer())
        for e in TestDeterministicReplay._sequence(self):
            x.ingest(e)
        written = {p.relative_to(self.tmp).parts[0] for p in self.tmp.rglob("*")}
        self.assertEqual(written, {"store"})
        names = {p.name for p in (self.tmp / "store").iterdir()}
        self.assertEqual(names, {"exchange.jsonl", "exchange.lock", "payloads", "outputs"})


if __name__ == "__main__":
    unittest.main()
