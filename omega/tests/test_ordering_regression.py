"""Regression for the defect behind the Android result "94 passed, 1 failed"
(ROOT_CAUSE_REPORT.md): messages with the SAME sent_at were ordered by
event_id, a random hash, so about half the time a reply sorted before its
question. Its answer was then not extracted, and the context listed the
question as unanswered.

Each test repeats the scenario many times on fresh nodes: on the defective
code the chance that all repetitions pass by luck is about 2^-40."""
from omega.events import event_id_for
from omega.relationship import RelationshipMemory
from omega.tests.conftest import HUMAN, make_node, pair, run_pipe_sync

SAME_SECOND = "2026-11-10T10:00:00Z"
TRIALS = 40


def _qa(rm, cid, tag=""):
    q = rm.record_message(cid, direction="OUT", text="Hi Sam, what budget do you have in mind?", sent_at=SAME_SECOND,
                          source_ref=f"sms:q{tag}", actor=HUMAN)
    a = rm.record_message(cid, direction="IN", text="Around $2,500 to start.", sent_at=SAME_SECOND,
                          source_ref=f"sms:a{tag}", actor="tool:import")
    return q, a


def test_reply_in_same_second_is_always_attributed_to_its_question(tmp_path):
    for i in range(TRIALS):
        n = make_node(tmp_path / f"n{i}", "phone")
        rm = RelationshipMemory(n)
        cid = rm.add_contact("Sam Lee", primary=f"sms:+1555000{i:04d}", actor=HUMAN)
        q, a = _qa(rm, cid)
        assert [(f.payload["attribute"], f.payload["value"]) for f in a["facts"]] == [("budget", "$2,500")], i
        ctx = rm.context(cid)
        assert [m["direction"] for m in ctx["timeline"]] == ["OUT", "IN"], i
        assert ctx["open_questions"] == [] and len(ctx["answered_questions"]) == 1, i
        assert "REPEATED_QUESTION" in {f["code"] for f in rm.check_draft(cid, "Hi Sam, how much budget do you have?")}
        n.close()


def test_tie_order_is_identical_on_both_devices_after_sync(tmp_path):
    for i in range(10):
        a, b = make_node(tmp_path / f"a{i}", "phone"), make_node(tmp_path / f"b{i}", "pc")
        pair(a, b)
        rm = RelationshipMemory(a)
        cid = rm.add_contact("Sam Lee", primary="sms:+15550001", actor=HUMAN)
        _qa(rm, cid)
        run_pipe_sync(a, b)
        ta = [m["event_id"] for m in rm.context(cid)["timeline"]]
        tb = [m["event_id"] for m in RelationshipMemory(b).context(cid)["timeline"]]
        assert ta == tb and rm.context_digest(cid) == RelationshipMemory(b).context_digest(cid)
        a.close(); b.close()
