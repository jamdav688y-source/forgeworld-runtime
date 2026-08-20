import unittest
from datetime import datetime, timedelta, timezone

from agent_mesh.session_mesh import (
    GovernedMessage,
    InboundDisposition,
    LifecycleState,
    SessionIdentity,
    decide_inbound,
    transition_lifecycle,
    validate_message,
)


class SessionMeshTests(unittest.TestCase):
    def setUp(self):
        self.recipient = SessionIdentity(
            "builder", "IMPLEMENTER", "jamdav688y-source/forgeworld-runtime",
            "feature/fw-cap-dispatch-004", "LOCAL", "LOCAL_SOCKET", True,
            ("repository_edit",),
        )
        self.message = GovernedMessage(
            mission_id="FW-AGENT-MESH-005", sender_session="architect",
            recipient_session="builder", intent="IMPLEMENT",
            requested_capability="repository_edit", content="Implement the bounded change.",
        )

    def test_receipt_never_executes(self):
        result = decide_inbound(self.message, recipient=self.recipient,
                                transport_setting="accept", authority_permits=True, queue_depth=0)
        self.assertEqual(result["disposition"], InboundDisposition.ACCEPT_BOUNDED.value)
        self.assertFalse(result["execute"])

    def test_missing_authority_holds(self):
        result = decide_inbound(self.message, recipient=self.recipient,
                                transport_setting="accept", authority_permits=False, queue_depth=0)
        self.assertEqual(result["disposition"], InboundDisposition.HOLD_FOR_REVIEW.value)

    def test_refuse_is_preserved(self):
        result = decide_inbound(self.message, recipient=self.recipient,
                                transport_setting="refuse", authority_permits=True, queue_depth=0)
        self.assertEqual(result["disposition"], InboundDisposition.REFUSE.value)

    def test_duplicate_is_quarantined(self):
        key = self.message.to_dict()["idempotency_key"]
        result = decide_inbound(self.message, recipient=self.recipient,
                                transport_setting="accept", authority_permits=True,
                                queue_depth=0, seen_idempotency_keys=[key])
        self.assertEqual(result["disposition"], InboundDisposition.QUARANTINE.value)

    def test_expired_message_fails_validation(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        message = GovernedMessage(
            mission_id="M", sender_session="a", recipient_session="b", intent="REVIEW",
            requested_capability="read", content="x", ttl_seconds=1, created_at=old.isoformat(),
        )
        self.assertIn("message expired", validate_message(message))

    def test_lifecycle_is_sequential_and_evidenced(self):
        with self.assertRaises(ValueError):
            transition_lifecycle(LifecycleState.REQUEST, LifecycleState.EXECUTING)
        with self.assertRaises(ValueError):
            transition_lifecycle(LifecycleState.EXECUTING, LifecycleState.EVIDENCE_ATTACHED)
        result = transition_lifecycle(
            LifecycleState.EXECUTING, LifecycleState.EVIDENCE_ATTACHED,
            evidence_refs=["EVD-001"],
        )
        self.assertEqual(result["to"], "EVIDENCE_ATTACHED")


if __name__ == "__main__":
    unittest.main()
