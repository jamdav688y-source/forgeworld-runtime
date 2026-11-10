"""FINAL ACCEPTANCE: the complete phone-offline -> sync -> PC -> authorized
response scenario (omega/demo_e2e.py), asserted step by step."""
from omega import demo_e2e


def test_end_to_end_acceptance(tmp_path):
    r = demo_e2e.run(tmp_path)
    phone, pc = r["_nodes"]
    try:
        # captured on the phone, offline, with provenance
        assert r["phone_offline_integrity"]
        assert ("budget", "$5,000") in r["extracted_facts"]
        assert any(a == "boundary:call" for a, _ in r["extracted_facts"])
        # the phone avoids the repetition and the boundary
        assert r["naive_draft_blocked"] == ["BOUNDARY_CONFLICT", "REPEATED_QUESTION"]
        assert "budget" not in r["phone_draft"].lower().split("noted on your budget")[0]
        assert r["phone_draft_next_question"] == "goal"
        # authenticated sync, verified evidence, identical reconstruction
        assert r["sync_complete"] and r["pc_imported"] > 0 and r["pc_integrity"]
        assert r["pc_provenance_chain"] == {"fact_value": "$5,000", "fact_rests_on_message": True,
                                            "message_source": "sms:thread-77/msg-2", "raw_artifact_matches": True,
                                            "message_signed_by_phone": True}
        assert r["same_context"]
        # bounded execution under human control
        assert r["before_authorization"] == "AWAITING_AUTHORIZATION" and r["outbox_before_authorization"] == 0
        assert r["after_authorization"] == "SUCCEEDED"
        assert r["pc_known_facts"] == ["boundary:call", "budget", "goal"]
        reply = r["sent_reply"]
        assert reply != r["phone_draft"]                                   # it moved on
        assert reply.startswith("Hi Dana,")
        assert "Noted on your goal: Cutting our customer onboarding time in half.\n" in reply
        assert "What timeline are you working towards?" in reply           # next open question
        assert "budget range" not in reply and "successful outcome" not in reply  # nothing re-asked
        assert "call" not in reply.lower()                                 # boundary respected
        assert r["sent_reply_findings"] == []
        # convergence + receipts for every material transition
        assert r["sync_back_complete"] and r["vectors_equal"] and r["state_digests_equal"] and r["final_integrity"]
        for t in ("EVENT_APPENDED", "SYNC_SESSION"):
            assert t in r["phone_receipt_types"] and t in r["pc_receipt_types"]
        assert "TASK_HELD_FOR_AUTHORIZATION" in r["pc_receipt_types"]
    finally:
        phone.close()
        pc.close()
