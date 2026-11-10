"""Stage F: relationship memory -- answered-question detection, identity,
cross-contact privacy isolation, boundaries, novelty, obligations."""
import pytest

from omega.relationship import RelationshipMemory, classify_question
from omega.tests.conftest import HUMAN

IMPORT = "tool:sms-import"


@pytest.fixture
def mem(phone):
    rm = RelationshipMemory(phone)
    dana = rm.add_contact("Dana Reyes", primary="sms:+15550100", aliases=["Dee"], actor=HUMAN)
    sam = rm.add_contact("Samuel Okafor", primary="sms:+15550199", actor=HUMAN)
    rm.record_message(dana, direction="OUT", text="Hi Dana, thanks for the chat. What budget do you have in mind?",
                      sent_at="2026-11-01T10:00:00Z", source_ref="sms:dana#1", actor=HUMAN)
    rm.record_message(dana, direction="IN", text="Around $5,000 for phase one. Please don't call me, text is best.",
                      sent_at="2026-11-01T10:30:00Z", source_ref="sms:dana#2", actor=IMPORT)
    rm.record_message(sam, direction="IN", text="My email is sam@okafor-legal.example and our budget is 40k.",
                      sent_at="2026-11-01T11:00:00Z", source_ref="sms:sam#1", actor=IMPORT)
    rm.assert_fact(sam, "diagnosis", "recovering from knee surgery", basis="OPERATOR", actor=HUMAN)
    return rm, dana, sam


def codes(findings, severity=None):
    return sorted({f["code"] for f in findings if severity is None or f["severity"] == severity})


def test_answer_is_extracted_with_provenance(mem):
    rm, dana, _ = mem
    ctx = rm.context(dana)
    b = ctx["facts"]["budget"]
    assert (b["value"], b["status"]) == ("$5,000", "RESOLVED")
    msg_ids = [m["event_id"] for m in ctx["timeline"] if m["direction"] == "IN"]
    assert msg_ids[0] in b["evidence"]
    assert ctx["timeline"][1]["source"] == "sms:dana#2"
    assert ctx["answered_questions"][0]["attribute"] == "budget"


def test_previously_answered_question_is_detected_even_when_reworded(mem):
    rm, dana, _ = mem
    for draft in ("Hi Dana, what's your budget for this?",
                  "Hi Dana, how much are you willing to spend?",
                  "Hi Dee, could you share your price range?"):
        f = rm.check_draft(dana, draft)
        assert "REPEATED_QUESTION" in codes(f, "BLOCK"), draft
    ok = rm.check_draft(dana, "Hi Dana, what timeline are you working towards?")
    assert "REPEATED_QUESTION" not in codes(ok)


def test_pending_question_warns_instead_of_nagging(phone):
    rm = RelationshipMemory(phone)
    c = rm.add_contact("Lee Park", primary="sms:+15550111", actor=HUMAN)
    rm.record_message(c, direction="OUT", text="Hi Lee, when do you need this finished?", sent_at="2026-11-01T10:00:00Z",
                      source_ref="sms:lee#1", actor=HUMAN)
    f = rm.check_draft(c, "Hi Lee, what's your deadline?")
    assert codes(f) == ["ALREADY_ASKED_PENDING"]


def test_mistaken_identity_is_blocked(mem):
    rm, dana, _ = mem
    assert "MISTAKEN_IDENTITY" in codes(rm.check_draft(dana, "Hi Samuel, following up on our chat."), "BLOCK")
    assert "MISTAKEN_IDENTITY" in codes(rm.check_draft(dana, "Hello Diana, quick update."), "BLOCK")
    assert codes(rm.check_draft(dana, "Hi Dee, quick update."), "BLOCK") == []


def test_boundary_and_contradiction_are_blocked(mem):
    rm, dana, _ = mem
    assert "BOUNDARY_CONFLICT" in codes(rm.check_draft(dana, "Hi Dana, can I call you tomorrow?"), "BLOCK")
    assert "CONTRADICTION" in codes(rm.check_draft(dana, "Hi Dana, given your budget of $3,000 we can..."), "BLOCK")
    assert "CONTRADICTION" not in codes(rm.check_draft(dana, "Hi Dana, given your budget of 5k we can..."))


def test_cross_contact_privacy_isolation(mem):
    rm, dana, sam = mem
    ctx = rm.context(dana)
    blob = repr(ctx)
    for leaked in ("okafor", "40k", "knee", "sam@"):
        assert leaked not in blob.lower()
    assert all(m["text"].startswith(("Hi Dana", "Around")) for m in ctx["timeline"])
    f = rm.check_draft(dana, "Hi Dana, by the way Samuel is recovering from knee surgery.")
    assert "PRIVACY_LEAK" in codes(f, "BLOCK")
    assert "CROSS_CONTACT_REFERENCE" in codes(f)
    f2 = rm.check_draft(dana, "Hi Dana, I'll send it to sam@okafor-legal.example too.")
    assert "PRIVACY_LEAK" in codes(f2, "BLOCK")
    # contact-scoped search
    assert phone_search(rm, "surgery", dana) == []
    assert phone_search(rm, "surgery", sam)


def phone_search(rm, q, cid):
    return rm.node.search(q, entity=f"contact:{cid}")


def test_novelty_and_idempotent_message_capture(mem):
    rm, dana, _ = mem
    again = rm.record_message(dana, direction="IN", text="Around $5,000 for phase one. Please don't call me, text is best.",
                              sent_at="2026-11-01T10:30:00Z", source_ref="sms:dana#2", actor=IMPORT)
    assert again["status"] == "DUPLICATE"
    near = rm.record_message(dana, direction="IN", text="Around $5,000 for phase one. Please don't call me, text is best!!",
                             sent_at="2026-11-02T09:00:00Z", source_ref="sms:dana#3", actor=IMPORT)
    assert near["novelty"]["class"] == "EXACT_DUPLICATE"  # normalized text identical
    new = rm.record_message(dana, direction="IN", text="Also, we would like to launch before the spring trade show.",
                            sent_at="2026-11-02T09:05:00Z", source_ref="sms:dana#4", actor=IMPORT)
    assert new["novelty"]["class"] == "NOVEL"


def test_obligations_surface_and_overdue(mem):
    rm, dana, _ = mem
    cm = rm.add_commitment(dana, "send the phase-one proposal", owed_by="US", due="2026-11-05", actor=HUMAN)
    f = rm.check_draft(dana, "Hi Dana, hope your week is going well.", today="2026-11-10")
    assert "OVERDUE_OBLIGATION" in codes(f)
    rm.set_commitment_status(dana, cm, "DONE", actor=HUMAN)
    assert "OVERDUE_OBLIGATION" not in codes(rm.check_draft(dana, "Hi Dana, hello.", today="2026-11-10"))


def test_deterministic_draft_advances_instead_of_repeating(mem):
    rm, dana, _ = mem
    d = rm.compose(dana, "discovery", sender="J.")
    assert d["text"].startswith("Hi Dana,")
    assert "budget" not in d["next_question"]
    assert d["next_question"] == "goal"
    assert codes(d["findings"], "BLOCK") == []
    assert "Noted on your budget: $5,000." in d["text"]


def test_generator_output_that_repeats_a_question_is_rejected(mem):
    rm, dana, _ = mem

    def bad(ctx, intent):
        return "Hi Dana, what's your budget?"
    bad.name = "fake-llm"
    d = rm.compose(dana, "discovery", generator=bad)
    assert d["generator"] == "deterministic-template"
    assert d["generator_rejected"]["codes"] == ["REPEATED_QUESTION"]

    def broken(ctx, intent):
        raise ConnectionError("model offline")
    d2 = rm.compose(dana, "discovery", generator=broken)
    assert d2["generator"] == "deterministic-template" and "unavailable" in d2["generator_rejected"]["reason"]


def test_question_classifier_examples():
    assert classify_question("What's your budget?") == "budget"
    assert classify_question("When do you need it?") == "timeline"
    assert classify_question("Where are you based?") == "location"
    assert classify_question("Did you enjoy the weekend?") is None


def test_every_template_question_classifies_to_its_own_attribute():
    """Invariant: if the composer asks it, the memory can recognise the answer
    and will never ask it again (found by the e2e test: an unclassified
    template question was re-asked and the send was blocked)."""
    from omega.relationship import QUESTION_TEMPLATES
    for attr, q in QUESTION_TEMPLATES.items():
        assert classify_question(q) == attr, (attr, q)


def test_semantic_checker_is_advisory_and_degrades(mem):
    rm, dana, _ = mem
    seen = []

    def checker(pairs, q):
        seen.append((len(pairs), q))
        return "spend" in q
    checker.name = "fake-semantic"
    f = rm.check_draft(dana, "Hi Dana, what kind of spend approval process do you have?", semantic_checker=checker)
    assert [x for x in f if x["code"] == "POSSIBLE_REPEAT"][0]["severity"] == "WARN"
    assert seen and seen[0][0] >= 1                        # it saw the answered pairs of THIS contact only

    def broken(pairs, q):
        raise ConnectionError("model down")
    f2 = rm.check_draft(dana, "Hi Dana, what kind of spend approval process do you have?", semantic_checker=broken)
    assert "SEMANTIC_CHECK_UNAVAILABLE" in codes(f2) and "POSSIBLE_REPEAT" not in codes(f2)
