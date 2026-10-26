"""S1 audience signal intake tests: the two identity systems, duplicate
imports, shared-source lineage, provenance and privacy rejection, separation
of engagement metrics, the R4 bridge, the commercial boundary, and the first
YouTube feedback cycle. Synthetic fixtures only; temporary stores only."""
import shutil
import tempfile
import unittest
from pathlib import Path

from cognition import audience as au, commerce, cxp, cycle, exchange, governor as gv, lineage
from cognition.tests import _events as ev
from cognition.tests.test_exchange import snapshot

TOPIC = "Receiver-held authorization in ForgeWorld"
QUESTION = "What stops a compromised phone from replaying an old grant?"


def item(**overrides):
    base = {"platform": au.YOUTUBE, "question": QUESTION, "platform_event_ref": "yt-comment-0001",
            "context_ref": "video-fw-ep001", "author_ref": "author-viewer-a", "posted_at": "2026-10-17T06:30:00Z",
            "acquisition": "SYNTHETIC_FIXTURE"}
    base.update(overrides)
    return base


def video_observation():
    return ev.observation(statement="Episode 1 explains why the receiver, not the requester, holds the grant.",
                          sources=[ev.source("youtube:video-fw-ep001", source_type="platform_event")])


class AudienceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cxp-s1-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.x, self.g, self.runner, self.intake = self.make(self.tmp / "a")

    def make(self, root, **policy):
        x = exchange.CognitiveExchange(root / "store")
        g = gv.RecursionGovernor(x, root / "governor", gv.GovernorPolicy("policy-governor-v1", "operator-synthetic", **policy))
        return x, g, cycle.CycleRunner(x, g, root / "artifacts"), au.AudienceIntake(x, root / "audience")

    def imported(self, items, batch="batch-001", at="2026-10-17T07:05:00Z", intake=None):
        return (intake or self.intake).import_batch(batch, items, at)

    def rejected(self, raw_item, code):
        result = self.imported([raw_item])["results"][0]
        self.assertEqual((result["status"], result["error_code"]), (au.REJECTED, code), result.get("detail"))


class TestTwoIdentitySystems(AudienceTestCase):
    def test_reimporting_the_same_event_is_a_duplicate_import(self):
        first = self.imported([item()])
        again = self.imported([item()], batch="batch-002", at="2026-10-18T07:05:00Z")
        self.assertEqual(again["counts"], {au.ACCEPTED: 0, au.DUPLICATE_IMPORT: 1, au.REJECTED: 0})
        self.assertEqual(again["results"][0]["record_id"], first["results"][0]["record_id"])
        self.assertNotEqual(again["results"][0]["occurrence_id"], first["results"][0]["occurrence_id"])
        self.assertEqual(len(self.x.all_record_metadata()), 1)
        same_batch_replay = self.imported([item()])
        self.assertEqual(same_batch_replay["counts"][au.DUPLICATE_IMPORT], 1)

    def test_equal_questions_from_distinct_people_are_two_records_one_topic(self):
        report = self.imported([item(), item(platform_event_ref="yt-comment-0002", author_ref="author-viewer-b")])
        self.assertEqual((report["distinct_records"], report["distinct_topics"], report["independent_origins"]), (2, 1, 2))

    def test_equal_questions_are_one_research_topic_for_r4(self):
        report = self.imported([item(), item(platform_event_ref="yt-comment-0002", author_ref="author-viewer-b")])
        q1, q2 = (r["record_id"] for r in report["results"])
        first = self.intake.research_cycle(self.runner, [q1], TOPIC, "2026-10-17T08:00:00Z")
        second = self.intake.research_cycle(self.runner, [q2], TOPIC, "2026-10-17T09:00:00Z")
        self.assertEqual(first["termination"], cycle.COMPLETED_WITH_CANDIDATES)
        self.assertEqual((second["termination"], second["detail"]), (cycle.REFUSED, gv.R_DUPLICATE))
        self.assertEqual(second["governor_decision"]["cycle_id"], first["governor_decision"]["cycle_id"])

    def test_reposts_share_their_original_origin(self):
        repost = item(platform_event_ref="yt-comment-0099", author_ref="author-viewer-z", reposted_from="yt-comment-0001")
        report = self.imported([repost, item()])  # repost listed first; originals are processed first
        self.assertEqual(report["counts"][au.ACCEPTED], 2)
        self.assertEqual(report["independent_origins"], 1)
        ids = [r["record_id"] for r in report["results"]]
        shared = lineage.shared_origins(self.x.record_metadata, ids)
        self.assertEqual((shared["independent_origin_count"], len(shared["repeated_origins"])), (1, 1))

    def test_cross_platform_copies_need_a_declared_origin(self):
        fb = item(platform=au.FACEBOOK, platform_event_ref="fb-post-77", author_ref=None)
        li = item(platform=au.LINKEDIN, platform_event_ref="li-post-77", author_ref=None)
        undeclared = self.imported([fb, li])
        self.assertEqual((undeclared["distinct_records"], undeclared["distinct_topics"], undeclared["independent_origins"]), (2, 1, 2))
        declared = self.imported([dict(fb, platform_event_ref="fb-post-78", origin_ref="origin-xpost-001"),
                                  dict(li, platform_event_ref="li-post-78", origin_ref="origin-xpost-001")], batch="batch-002")
        self.assertEqual(declared["independent_origins"], 1)

    def test_missing_metadata_is_left_missing_not_invented(self):
        bare = item(platform_event_ref=None, author_ref=None, posted_at=None, context_ref=None)
        first = self.imported([bare])["results"][0]
        record = self.x.get_record(first["record_id"])
        self.assertEqual({k: record.payload()[k] for k in ("platform_event_ref", "author_ref", "posted_at", "context_ref")},
                         {"platform_event_ref": None, "author_ref": None, "posted_at": None, "context_ref": None})
        self.assertTrue(record.sources[0].locator.startswith("youtube:unreferenced:"))
        self.assertEqual(self.imported([bare], batch="batch-002")["results"][0]["status"], au.DUPLICATE_IMPORT)


class TestProvenanceAndPrivacy(AudienceTestCase):
    def test_malformed_provenance(self):
        cases = {
            "unknown platform": item(platform="TIKTOK"),
            "scraped": item(acquisition="SCRAPED"),
            "api": item(acquisition="AUTHORIZED_API"),
            "missing acquisition": item(acquisition=None),
            "named author": item(author_ref="Jane Doe"),
            "handle as author": item(author_ref="@janedoe"),
            "bad timestamp": item(posted_at="yesterday"),
            "bad event ref": item(platform_event_ref="no spaces allowed"),
            "self repost": item(reposted_from="yt-comment-0001"),
            "engagement inside question": item(likes=1200),
            "flag not boolean": item(commercial_interest="yes"),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.rejected(raw, cxp.E_MALFORMED)
        self.rejected(item(origin_ref="Origin One"), cxp.E_MALFORMED)
        self.assertEqual(self.x.all_record_metadata(), ())

    def test_private_details_are_refused(self):
        for text in ("Can @janedoe explain the grant store?", "Email me at viewer@example.com about grants",
                     "Call 415 555 0134 if the grant expires"):
            with self.subTest(text):
                self.rejected(item(question=text), cxp.E_SENSITIVE_DATA)
        self.rejected(item(privacy=cxp.PRIV_PERSONAL), cxp.E_PRIVACY_CONSENT_REQUIRED)
        self.rejected(item(privacy=cxp.PRIV_RESTRICTED), cxp.E_PRIVACY_PERSISTENCE_UNSUPPORTED)
        self.assertEqual(self.x.all_record_metadata(), ())

    def _raw(self, **overrides):
        raw = self.intake.question_event(item(), "batch-001", "2026-10-17T07:05:00Z")
        raw.update(overrides)
        return raw

    def test_fabricated_verification_and_labels_are_refused(self):
        content_id = cxp.parse_event(self._raw())[0].content_id
        vr = self.x.ingest(ev.verification_result(content_id)).record_id
        cases = {
            "verified": (self._raw(verification=cxp.VER_VERIFIED, verification_ref=vr), cxp.E_KIND_RULE),
            "interpretation": (self._raw(provenance=cxp.UNVERIFIED_INTERPRETATION), cxp.E_KIND_RULE),
            "derived": (self._raw(provenance=cxp.DERIVED), cxp.E_KIND_RULE),
            "inference": (self._raw(representation=cxp.REP_INFERENCE), cxp.E_KIND_RULE),
            "evidence inflation": (self._raw(evidence=cxp.EV_INDEPENDENT_SOURCES), cxp.E_EVIDENCE_INFLATION),
            "forged locator": (self._raw(sources=[{"source_type": "platform_event", "locator": "youtube:someone-else"}]),
                               cxp.E_KIND_RULE),
            "extra source": (self._raw(sources=[{"source_type": "platform_event", "locator": "youtube:yt-comment-0001"},
                                                {"source_type": "document", "locator": "press-release"}]), cxp.E_KIND_RULE),
        }
        for name, (raw, code) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.x.ingest(raw).error_code, code)


class TestEngagementIsNotEvidence(AudienceTestCase):
    def test_metrics_live_apart_and_change_nothing(self):
        q = self.imported([item()])["results"][0]["record_id"]
        exchange_before = self.x.state_digest()
        governor_before = self.g.ledger_entries()
        entry = self.intake.record_engagement(au.YOUTUBE, "video-fw-ep001", "views", 250000, "2026-10-17T07:00:00Z", "batch-001")
        self.intake.record_engagement(au.YOUTUBE, "yt-comment-0001", "likes", 9000, "2026-10-17T07:00:00Z", "batch-001")
        self.assertEqual(entry["evidence_status"], "NOT_EVIDENCE")
        self.assertEqual((self.x.state_digest(), self.g.ledger_entries()), (exchange_before, governor_before))
        self.assertEqual(len(self.intake.engagement()), 2)
        self.intake.record_engagement(au.YOUTUBE, "video-fw-ep001", "views", 250000, "2026-10-17T07:00:00Z", "batch-001")
        self.assertEqual(len(self.intake.engagement()), 2)  # idempotent
        meta = self.x.record_metadata(q)
        self.assertEqual((meta["evidence"], meta["verification"]), (cxp.EV_SINGLE_SOURCE, cxp.VER_UNVERIFIED))

    def test_bad_metrics_are_refused(self):
        for args in ((au.YOUTUBE, "video-1", "revenue", 5, "2026-10-17T07:00:00Z", "b-1"),
                     (au.YOUTUBE, "video-1", "views", -1, "2026-10-17T07:00:00Z", "b-1"),
                     (au.YOUTUBE, "video-1", "views", 1.5, "2026-10-17T07:00:00Z", "b-1"),
                     ("MYSPACE", "video-1", "views", 1, "2026-10-17T07:00:00Z", "b-1")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.intake.record_engagement(*args)


class TestGovernedBridge(AudienceTestCase):
    def test_bridge_only_offers_audience_questions(self):
        obs = self.x.ingest(video_observation()).record_id
        q = self.imported([item()])["results"][0]["record_id"]
        for bad in ([obs], ["cxp-rec-" + "0" * 64], [], [q] * 1 + [f"cxp-rec-{i:064x}" for i in range(8)]):
            with self.subTest(bad=bad[:2]), self.assertRaises(ValueError):
                self.intake.research_cycle(self.runner, bad, TOPIC, "2026-10-17T08:00:00Z")
        self.x.erase(q, "synthetic-erasure")
        with self.assertRaises(ValueError):
            self.intake.research_cycle(self.runner, [q], TOPIC, "2026-10-17T08:00:00Z")

    def test_commercial_interest_waits_for_a_human_and_creates_no_commerce(self):
        q = self.imported([item(question="Could you run this diagnostic for my company?", platform=au.LINKEDIN,
                                platform_event_ref="li-comment-5", commercial_interest=True)])["results"][0]["record_id"]
        held = self.intake.research_cycle(self.runner, [q], TOPIC, "2026-10-17T08:00:00Z")
        self.assertEqual((held["termination"], held["governor_decision"]["reason_code"]), (cycle.AWAITING_HUMAN, gv.R_COMMERCIAL))
        self.assertEqual(held["governor_decision"]["evidence_refs"]["commercial_records"], [q])
        self.assertFalse(any(m["kind"] == cxp.KIND_COMMERCIAL_SIGNAL for m in self.x.all_record_metadata()))
        approval = self.g.record_approval(held["governor_decision"]["cycle_id"], gv.R_COMMERCIAL, "operator-synthetic")
        done = self.intake.research_cycle(self.runner, [q], TOPIC, "2026-10-17T09:00:00Z", approval_id=approval)
        self.assertEqual(done["governor_decision"]["reason_code"], gv.R_APPROVED)
        self.assertFalse(any(m["kind"] == cxp.KIND_COMMERCIAL_SIGNAL for m in self.x.all_record_metadata()))
        self.assertFalse(done["grants_execution_authority"])

    def test_audience_records_cannot_become_commercial_records(self):
        self.imported([item()])
        with self.assertRaises(KeyError):
            commerce.engagement_state(self.x, "eng-from-audience")
        self.assertFalse(self.intake.grants_execution_authority)
        for name in dir(au.AudienceIntake):
            for word in ("publish", "post", "reply", "contact", "execute", "scrape", "fetch", "approve"):
                self.assertNotIn(word, name.lower())


class TestFirstFeedbackCycle(AudienceTestCase):
    def test_youtube_topic_to_audience_question_to_research_candidate(self):
        # 1. a YouTube research topic, governed root cycle
        root = self.runner.run([video_observation()], TOPIC, "2026-10-17T07:00:00Z")
        self.assertEqual(root["termination"], cycle.COMPLETED_WITH_CANDIDATES)
        # 2. one audience question, manually exported
        report = self.imported([item()])
        q = report["results"][0]["record_id"]
        meta = self.x.record_metadata(q)
        # 3. CXP classification
        self.assertEqual((meta["kind"], meta["evidence"], meta["verification"], meta["provenance"]),
                         (cxp.KIND_AUDIENCE_QUESTION, cxp.EV_SINGLE_SOURCE, cxp.VER_UNVERIFIED, cxp.OBSERVED))
        # 4-6. seven lenses, contradictions preserved, R4 admission as a governed child cycle
        child = self.intake.research_cycle(self.runner, [q], TOPIC, "2026-10-17T08:00:00Z",
                                           parent_cycle_id=root["next_cycle"]["parent_cycle_id"])
        d = child["governor_decision"]
        self.assertEqual((d["decision"], d["depth"], d["evidence_refs"]["new_observation_roots"]), (gv.ADMIT, 1, [q]))
        self.assertEqual(sum(r["status"] == "PRODUCED" for r in child["lens_runs"]), 7)
        self.assertTrue(child["preserved_disagreements"])
        self.assertEqual({p["status"] for p in child["preserved_disagreements"]}, {"OPEN"})
        # 7. one traceable research candidate
        self.assertTrue(child["research_candidates"])
        self.assertEqual(child["evidence_classification"][0]["sources"][0]["locator"], "youtube:yt-comment-0001")
        self.assertEqual(self.runner.load(child["artifact_id"]), child)

    def test_reposts_of_already_used_questions_add_no_evidence(self):
        root = self.runner.run([video_observation()], TOPIC, "2026-10-17T07:00:00Z")
        q = self.imported([item()])["results"][0]["record_id"]
        child = self.intake.research_cycle(self.runner, [q], TOPIC, "2026-10-17T08:00:00Z",
                                           parent_cycle_id=root["next_cycle"]["parent_cycle_id"])
        repost = self.imported([item(platform_event_ref="yt-comment-0100", author_ref="author-viewer-y",
                                     reposted_from="yt-comment-0001", question="Same worry: what stops a replayed grant?")],
                               batch="batch-002")["results"][0]["record_id"]
        grandchild = self.intake.research_cycle(self.runner, [repost], TOPIC, "2026-10-17T09:00:00Z",
                                                parent_cycle_id=child["governor_decision"]["cycle_id"])
        self.assertEqual((grandchild["termination"], grandchild["detail"]), (cycle.REFUSED, gv.R_NO_NEW_EVIDENCE))

    def test_independent_runs_are_identical(self):
        def run(root):
            x, g, runner, intake = self.make(root)
            top = runner.run([video_observation()], TOPIC, "2026-10-17T07:00:00Z")
            q = intake.import_batch("batch-001", [item()], "2026-10-17T07:05:00Z")["results"][0]["record_id"]
            return intake.research_cycle(runner, [q], TOPIC, "2026-10-17T08:00:00Z",
                                         parent_cycle_id=top["next_cycle"]["parent_cycle_id"])
        self.assertEqual(run(self.tmp / "one"), run(self.tmp / "two"))
        self.assertEqual(snapshot(self.tmp / "one"), snapshot(self.tmp / "two"))


if __name__ == "__main__":
    unittest.main()
