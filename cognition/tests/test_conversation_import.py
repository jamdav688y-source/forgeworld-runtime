"""IMPORT-1: governed local import of operator-supplied conversations
(LinkedIn data-export CSV and plain-text records). Synthetic fixtures only:
invented people, example.invalid profile URLs, temporary stores; no network,
LinkedIn, Zapier, contact or platform access."""
from collections import Counter
from pathlib import Path
from unittest import mock

from cognition import conversation_import as ci, cxp, delivery as dv, destination as ds
from cognition.tests.test_engagement import EngagementTestCase
from cognition.tests.test_exchange import snapshot
from cognition.tests.test_odcc import ENG, T

HARBOR, HARBOR_ENG, HARBOR_ACCT = "customer-synthetic-harbor-dental", "eng-synthetic-harbor", "acct-synthetic-harbor"
LEDGER, LEDGER_ENG, LEDGER_ACCT = "customer-synthetic-ledgerline", "eng-synthetic-ledgerline", "acct-synthetic-ledgerline"
OPERATOR = "operator-engagement-lead"
DANA = "https://profiles.example.invalid/in/synthetic-dana"
SAM = "https://profiles.example.invalid/in/synthetic-sam"
ME = "https://profiles.example.invalid/in/synthetic-operator"

HEADER = "CONVERSATION ID,CONVERSATION TITLE,FROM,SENDER PROFILE URL,TO,RECIPIENT PROFILE URLS,DATE,SUBJECT,CONTENT,FOLDER\n"
DANA_1 = 'Our front desk loses "call-back" requests, maybe 1 in 10.\nWe track them on paper — café notes, too.'
ME_1 = "  Thanks. Could you say which step loses them?  "  # surrounding spaces are content
DANA_2 = "Between the phone and the scheduling screen, I think."
SAM_1 = "We need our evidence filed per audit, not per month."
ROWS = {
    "dana1": f'conv-synth-harbor,,Dana (synthetic),{DANA},Operator,{ME},2026-10-15 14:02:11 UTC,,"{DANA_1.replace(chr(34), chr(34) * 2)}",INBOX\n',
    "me1": f"conv-synth-harbor,,Operator (synthetic),{ME},Dana,{DANA},2026-10-15 15:10:00 UTC,,{ME_1},INBOX\n",
    "dana2": f"conv-synth-harbor,,Dana (synthetic),{DANA},Operator,{ME},2026-10-16 09:00:05 UTC,,\"{DANA_2}\",INBOX\n",
    "sam1": f"conv-synth-ledger,,Sam (synthetic),{SAM},Operator,{ME},2026-10-14 11:00:00 UTC,,{SAM_1},INBOX\n",
}
HARBOR_MAP = {DANA: "customer-author:dana", ME: f"operator:{OPERATOR}"}


def export(*keys) -> bytes:
    return (HEADER + "".join(ROWS[k] for k in keys)).encode()


TEXT = (f"CONVERSATION: conv-synth-harbor\n---\n"
        f"[2026-10-15T14:02:11Z] Dana: {DANA_1}\n\n"
        f"[2026-10-15T15:10:00Z] Operator: {ME_1}\n"
        f"[2026-10-16T09:00:05Z] Dana: {DANA_2}\n\n\n").encode()
TEXT_MAP = {"speaker:Dana": "customer-author:dana", "speaker:Operator": f"operator:{OPERATOR}"}


class ImportTestCase(EngagementTestCase):
    def setUp(self):
        super().setUp()
        self.open_store()

    def open_store(self, root=None):
        """(Re)open a store -- a restart when root is the current one, a clean store otherwise."""
        if root is not None:
            self.boot(root)
        self.importer = ci.ConversationImporter(self.x, self.g)
        # consent recorded up front, so refusal tests can assert that nothing at all was written
        self.consents = {eng: self.consent(engagement=eng, account=acct, entry=f"{eng}-consent")
                         for eng, acct in ((HARBOR_ENG, HARBOR_ACCT), (LEDGER_ENG, LEDGER_ACCT))}

    def binding(self, customer=HARBOR, engagement=HARBOR_ENG, **changes):
        kw = dict(customer_ref=customer, engagement_ref=engagement, participants=dict(HARBOR_MAP),
                  source_ref="linkedin-export:2026-10-19", synthetic=True, operator_id=OPERATOR, imported_at=T[1],
                  consent_record_id=self.consents.get(engagement))
        kw.update(changes)
        return kw

    def csv(self, data=None, conversation_id="conv-synth-harbor", **changes):
        return self.importer.import_linkedin_csv(data or export("dana1", "me1", "dana2", "sam1"),
                                                 conversation_id=conversation_id, **self.binding(**changes))

    def ledger_csv(self):
        return self.csv(conversation_id="conv-synth-ledger", customer=LEDGER, engagement=LEDGER_ENG,
                        participants={SAM: "customer-author:sam"})

    def kinds(self):
        return sorted(m["kind"] for m in self.x.all_record_metadata())

    def import_refused(self, fn, expected):
        self.refused(fn, expected, ci.ImportRefused)


class TestValidImports(ImportTestCase):
    def test_valid_csv_import_preserves_content_time_and_provenance(self):
        out = self.csv()
        self.assertEqual(out["counts"], {"IMPORTED": 3, "DUPLICATE_SUPPRESSED": 0})
        self.assertEqual((out["classified"], out["grants_execution_authority"]), (False, False))
        records = [self.x.get_record(m["record_id"]) for m in out["messages"]]
        metas = [self.x.record_metadata(m["record_id"]) for m in out["messages"]]
        self.assertEqual([r.payload()["statement"] for r in records], [DANA_1, ME_1, DANA_2])  # byte for byte
        self.assertEqual([m["kind"] for m in metas], [cxp.KIND_OBSERVATION] * 3)
        self.assertEqual({(r.representation, r.provenance, r.privacy) for r in records},
                         {(cxp.REP_QUOTATION, cxp.OBSERVED, cxp.PRIV_INTERNAL)})
        self.assertEqual({m["consent_ref"] for m in metas}, {self.binding()["consent_record_id"]})
        ids = [m["record_id"] for m in out["messages"]]
        observed = {e["record_id"]: e["observed_at"] for e in self.x.ledger_entries()
                    if e["entry"] == "OCCURRENCE" and e["record_id"] in ids}
        self.assertEqual([observed[i] for i in ids], ["2026-10-15T14:02:11Z", "2026-10-15T15:10:00Z", "2026-10-16T09:00:05Z"])
        for r in records:
            self.assertIn(f"source:linkedin-export:2026-10-19 imported_at:{T[1]}", r.payload()["subject"])
        locators = [sorted(s["locator"] for s in m["root_sources"]) for m in metas]
        file_locator = f"import-file:sha256:{out['file_sha256']}"
        self.assertEqual([l[1] if l[0] == file_locator else l[0] for l in locators],
                         [f"customer:{HARBOR}/conversation/conv-synth-harbor/{out['messages'][0]['message_id']}",
                          f"operator:{OPERATOR}/conversation/conv-synth-harbor/{out['messages'][1]['message_id']}",
                          f"customer:{HARBOR}/conversation/conv-synth-harbor/{out['messages'][2]['message_id']}"])
        self.assertTrue(all(file_locator in l for l in locators))
        # one person is one origin, however many messages and files mention them
        self.assertEqual({s["independence_key"] for m in (metas[0], metas[2]) for s in m["root_sources"]},
                         {f"customer:{HARBOR}/author/dana"})
        self.assertNotIn(SAM_1, [r.payload()["statement"] for r in records])  # other conversations untouched

    def test_message_ids_are_stable_across_stores(self):
        first = [(m["message_id"], m["record_id"]) for m in self.csv()["messages"]]
        self.open_store(self.tmp / "b")
        self.assertEqual([(m["message_id"], m["record_id"]) for m in self.csv()["messages"]], first)

    def test_valid_plain_text_import(self):
        out = self.importer.import_text(TEXT, **self.binding(participants=dict(TEXT_MAP),
                                                             source_ref="operator-record:harbor-2026-10-16"))
        self.assertEqual((out["conversation_id"], out["counts"]["IMPORTED"]), ("conv-synth-harbor", 3))
        self.assertEqual([self.x.get_record(m["record_id"]).payload()["statement"] for m in out["messages"]],
                         [DANA_1, ME_1, DANA_2])  # multi-line content kept; separator blank lines dropped


class TestRefusals(ImportTestCase):
    def test_missing_consent(self):
        self.import_refused(lambda: self.csv(consent_record_id=None), "CONSENT_RECORD_MISSING")
        other = self.consents[LEDGER_ENG]
        self.import_refused(lambda: self.csv(consent_record_id=other), "CONSENT_BELONGS_TO_ANOTHER_ENGAGEMENT")
        live = self.binding()["consent_record_id"]
        self.withdraw(live, HARBOR_ENG, HARBOR_ACCT)
        self.import_refused(lambda: self.csv(consent_record_id=live), "CONSENT_WITHDRAWN_OR_VOIDED")

    def test_wrong_customer(self):
        self.csv()
        binding = self.binding(customer=LEDGER, engagement=LEDGER_ENG)
        self.import_refused(lambda: self.importer.import_linkedin_csv(export("dana1", "me1", "dana2"),
                                                                      conversation_id="conv-synth-harbor", **binding),
                            "conversation conv-synth-harbor belongs to another customer")
        self.bound_spec()  # binds the synthetic engagement ENG to the fixture's customer
        consent = self.synthetic_consent()
        self.import_refused(lambda: self.csv(conversation_id="conv-synth-ledger", customer=LEDGER, engagement=ENG,
                                             participants={SAM: "customer-author:sam"}, consent_record_id=consent),
                            f"engagement {ENG} serves another customer")
        bad_flags = self.binding(customer="customer-ledgerline-real", synthetic=True)
        self.import_refused(lambda: self.importer.import_linkedin_csv(export("sam1"), conversation_id="conv-synth-ledger",
                                                                      **bad_flags), "synthetic flag disagree")

    def test_duplicate_message(self):
        out = self.csv(export("dana1", "dana1", "me1"))
        self.assertEqual([m["status"] for m in out["messages"]], ["IMPORTED", "DUPLICATE_SUPPRESSED", "IMPORTED"])
        self.assertEqual(out["messages"][0]["record_id"], out["messages"][1]["record_id"])
        later = self.csv(export("dana1", "me1", "dana2"))  # a later, overlapping export
        self.assertEqual(later["counts"], {"IMPORTED": 1, "DUPLICATE_SUPPRESSED": 2})

    def test_duplicate_conversation(self):
        self.csv()
        before, kinds = snapshot(self.root), self.kinds()
        again = self.csv()
        self.assertEqual(again["counts"], {"IMPORTED": 0, "DUPLICATE_SUPPRESSED": 3})
        as_text = self.importer.import_text(TEXT, **self.binding(participants=dict(TEXT_MAP),
                                                                 source_ref="operator-record:harbor-copy"))
        self.assertEqual(as_text["counts"], {"IMPORTED": 0, "DUPLICATE_SUPPRESSED": 3})  # same messages, other format
        self.assertEqual((snapshot(self.root), self.kinds()), (before, kinds))

    def test_malformed_timestamps(self):
        bad_csv = export("dana1").replace(b"2026-10-15 14:02:11 UTC", b"15/10/2026 14:02")
        self.import_refused(lambda: self.csv(bad_csv), "MALFORMED_TIMESTAMP")
        bad_text = TEXT.replace(b"[2026-10-15T15:10:00Z]", b"[yesterday 3pm]")
        self.import_refused(lambda: self.importer.import_text(bad_text, **self.binding(participants=dict(TEXT_MAP))),
                            "MALFORMED_TIMESTAMP")
        self.import_refused(lambda: self.csv(export("dana1").replace(b"2026-10-15 14:02:11 UTC", b"2026-02-30 10:00:00 UTC")),
                            "MALFORMED_TIMESTAMP")
        self.import_refused(lambda: self.csv(imported_at="today"), "imported_at")

    def test_malformed_input_and_overlong_content(self):
        self.import_refused(lambda: self.csv(b"FROM,CONTENT\nDana,hello\n"), "lacks columns")
        self.import_refused(lambda: self.importer.import_text(b"hello\n", **self.binding()), "MALFORMED_IMPORT")
        self.import_refused(lambda: self.csv(conversation_id="conv-does-not-exist"), "no messages")
        long_row = f"conv-synth-harbor,,Dana (synthetic),{DANA},Operator,{ME},2026-10-15 14:02:11 UTC,,{'x' * 8001},INBOX\n"
        self.import_refused(lambda: self.csv((HEADER + long_row).encode()), "never truncated")

    def test_missing_provenance(self):
        for value in (None, "", "export.csv", "linkedin-export: has space"):
            with self.subTest(value):
                self.import_refused(lambda: self.csv(source_ref=value), "MISSING_PROVENANCE")

    def test_ambiguous_identity(self):
        self.import_refused(lambda: self.csv(participants={DANA: "customer-author:dana"}), "unmapped author")
        self.import_refused(lambda: self.csv(participants={DANA: "Dana Harbor", ME: f"operator:{OPERATOR}"}),
                            "must be customer-author:<slug>")
        twin = ROWS["dana2"].replace(DANA, "https://profiles.example.invalid/in/synthetic-dana-2")
        self.import_refused(lambda: self.csv(export("dana1", "me1") + twin.encode(),
                                             participants={**HARBOR_MAP,
                                                           "https://profiles.example.invalid/in/synthetic-dana-2":
                                                               "customer-author:dana"}),
                            "display name 'Dana (synthetic)' maps to 2 identities")

    def test_cross_customer_artifact_reference(self):
        harbor = self.csv()["messages"]
        ledger = self.ledger_csv()["messages"]
        dana_msg, sam_msg = harbor[0]["record_id"], ledger[0]["record_id"]
        own = self.assemble(None, customer_ref=LEDGER, source_artifact_ids=[sam_msg])
        self.assertEqual(self.desk.status(own["package_id"])["status"], dv.VALIDATED)
        self.refused(lambda: self.assemble(None, customer_ref=LEDGER, source_artifact_ids=[sam_msg, dana_msg]),
                     "another customer's evidence", dv.DeliveryRefused)
        # the same rule holds for derived records: a cycle over Dana's words still names Dana's customer
        cycle = self.runner.run([], "Harbor (synthetic): lost call-back requests", T[2], extra_input_ids=[dana_msg])
        brief = self.make_brief(cycle["artifact_id"])
        self.refused(lambda: self.propose(brief, customer_ref=LEDGER), "another customer's evidence",
                     ds.DestinationRefused)
        self.propose(brief, customer_ref=HARBOR)  # the customer whose words they are: allowed

    def test_operator_messages_are_never_customer_evidence(self):
        mine = self.csv()["messages"][1]["record_id"]
        self.assertEqual(dv.customer_refs_of(self.x.record_metadata(mine)), set())
        self.assertEqual(dv.customer_refs_of(self.x.record_metadata(self.csv()["messages"][0]["record_id"])), {HARBOR})

    def test_replay_after_interruption(self):
        real_ingest, calls = self.x.ingest, []

        def failing(event):
            calls.append(event)
            if len(calls) == 2:
                raise OSError("simulated power loss")
            return real_ingest(event)

        with mock.patch.object(self.x, "ingest", side_effect=failing):
            with self.assertRaises(OSError):
                self.csv()
        self.open_store(self.root)  # restart from disk
        resumed = self.csv()
        self.assertEqual([m["status"] for m in resumed["messages"]], ["DUPLICATE_SUPPRESSED", "IMPORTED", "IMPORTED"])
        replayed = [m["record_id"] for m in resumed["messages"]]
        self.open_store(self.tmp / "clean")
        self.assertEqual([m["record_id"] for m in self.csv()["messages"]], replayed)  # same records as a clean run

    def test_import_during_a_running_cycle_is_refused(self):
        self.g._active_cycles += 1
        self.import_refused(lambda: self.csv(), "IMPORT_DURING_RUNNING_CYCLE")


class TestNoExternalActionNoInterpretation(ImportTestCase):
    def test_unauthorized_external_action(self):
        def no_network(*a, **k):
            raise AssertionError("network access attempted")
        # patched by name: the package guard forbids importing network modules, even in tests
        with mock.patch("socket.socket.connect", no_network), mock.patch("socket.create_connection", no_network), \
                mock.patch("urllib.request.urlopen", no_network):
            out = self.csv()
            self.importer.classify(out["messages"][0]["record_id"], "PROBLEM_STATEMENT", OPERATOR, T[2])
        self.assertFalse(self.importer.grants_execution_authority)
        verbs = ("send", "post", "publish", "deliver", "contact", "reply", "message", "upload", "fetch", "sync")
        self.assertEqual([n for n in dir(self.importer) if not n.startswith("_") and any(v in n.lower() for v in verbs)], [])
        for who in ("zapier-automation", "linkedin-bot", "operator-X", None):
            with self.subTest(who):
                self.import_refused(lambda: self.csv(operator_id=who), "UNAUTHORIZED_IMPORTER")
        self.import_refused(lambda: self.importer.classify(out["messages"][0]["record_id"], "OBJECTION",
                                                           "zapier-automation", T[3]), "UNAUTHORIZED_CLASSIFIER")
        source = Path(ci.__file__).read_text()
        for module in ("socket", "urllib", "http", "requests", "subprocess", "smtplib"):
            self.assertNotIn(f"import {module}", source)

    def test_import_never_interprets_or_qualifies(self):
        before = self.kinds()
        out = self.csv()
        added = Counter(self.kinds()) - Counter(before)
        self.assertEqual(added, Counter({cxp.KIND_OBSERVATION: 3}))  # no CLAIM, COMMERCIAL_SIGNAL, cycle or spec
        message = out["messages"][0]["record_id"]
        original = self.x.get_record(message).payload()
        claim = self.importer.classify(message, "PROBLEM_STATEMENT", OPERATOR, T[2])
        meta = self.x.record_metadata(claim)
        self.assertEqual(meta["kind"], cxp.KIND_CLAIM)
        record = self.x.get_record(claim)
        self.assertEqual((record.representation, record.provenance, record.derived_from),
                         (cxp.REP_INFERENCE, cxp.DERIVED, (message,)))
        self.assertEqual(self.x.get_record(message).payload(), original)  # interpretation never edits the message
        self.import_refused(lambda: self.importer.classify(message, "HOT_LEAD", OPERATOR, T[3]), "UNKNOWN_LABEL")
        for not_a_message in (self.binding()["consent_record_id"], claim):  # a label is not labelled again
            self.import_refused(lambda: self.importer.classify(not_a_message, "OTHER", OPERATOR, T[3]),
                                "NOT_AN_IMPORTED_MESSAGE")
        self.assertNotIn("QUALIFIED", " ".join(ci.LABELS))
