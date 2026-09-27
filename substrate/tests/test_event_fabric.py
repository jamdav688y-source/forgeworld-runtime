"""Event Fabric envelope contract tests (Sections 19-22)."""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from substrate import event_fabric as ef


class TestEnvelopeConstruction(unittest.TestCase):
    def test_all_ten_message_families_are_distinct_and_constructible(self):
        builders_and_types = [
            (lambda: ef.build_command(source_peer_id="P", destination_node_id="N", capability_id="c", fabric_request_id="r"), ef.MSG_COMMAND),
            (lambda: ef.build_event(source_peer_id="P", destination_node_id="N", description="d"), ef.MSG_EVENT),
            (lambda: ef.build_artifact(source_peer_id="P", destination_node_id="N", artifact_id="a", sha256="s"), ef.MSG_ARTIFACT),
            (lambda: ef.build_memory_delta(source_peer_id="P", destination_node_id="N", proposed_record={}, target_memory_class="EPISODIC"), ef.MSG_MEMORY_DELTA),
            (lambda: ef.build_capability_advertisement(
                source_peer_id="P", destination_node_id="N", capability_id="c", version="1",
                input_contract={}, output_contract={}, authority_requirement=(), availability="AVAILABLE",
                evidence_requirement=(), capability_state="DEMONSTRATED",
            ), ef.MSG_CAPABILITY_ADVERTISEMENT),
            (lambda: ef.build_workflow(source_peer_id="P", destination_node_id="N", workflow_plan_id="p", objective_id="o"), ef.MSG_WORKFLOW),
            (lambda: ef.build_result(source_peer_id="P", destination_node_id="N", execution_id="e", status="COMPLETED"), ef.MSG_RESULT),
            (lambda: ef.build_evidence_receipt(source_peer_id="P", destination_node_id="N", evidence_id="e"), ef.MSG_EVIDENCE_RECEIPT),
            (lambda: ef.build_heartbeat(source_peer_id="P", destination_node_id="N"), ef.MSG_HEARTBEAT),
            (lambda: ef.build_state_summary(source_peer_id="P", destination_node_id="N", summary={}), ef.MSG_STATE_SUMMARY),
        ]
        seen_types = set()
        for builder, expected_type in builders_and_types:
            envelope = builder()
            self.assertEqual(envelope.message_type, expected_type)
            seen_types.add(envelope.message_type)
        self.assertEqual(len(seen_types), 10)
        self.assertEqual(seen_types, set(ef.MESSAGE_TYPES))

    def test_rejects_unknown_message_type(self):
        with self.assertRaises(ef.EventFabricError):
            ef.MessageEnvelope(
                message_id=ef._new_id("MSG"), message_type="NOT_A_REAL_TYPE", source_peer_id="P",
                destination_node_id="N", payload={},
            )

    def test_rejects_non_dict_payload(self):
        with self.assertRaises(ef.EventFabricError):
            ef.MessageEnvelope(
                message_id=ef._new_id("MSG"), message_type=ef.MSG_EVENT, source_peer_id="P",
                destination_node_id="N", payload="not a dict",
            )

    def test_memory_delta_rejects_unknown_target_memory_class(self):
        with self.assertRaises(ef.EventFabricError):
            ef.build_memory_delta(source_peer_id="P", destination_node_id="N", proposed_record={}, target_memory_class="NOT_REAL")

    def test_every_envelope_carries_common_metadata(self):
        env = ef.build_workflow(source_peer_id="P", destination_node_id="N", workflow_plan_id="PLAN-1", objective_id="OBJ-1")
        for field_name in ("message_id", "message_type", "source_peer_id", "destination_node_id", "created_at", "schema_version"):
            self.assertTrue(hasattr(env, field_name))

    def test_command_names_the_real_fabric_request_by_id_not_duplicating_its_fields(self):
        cmd = ef.build_command(source_peer_id="P", destination_node_id="N", capability_id="physical_ping", fabric_request_id="CAPREQ-123")
        # Deliberately does NOT carry integrity_tag/relationship_id/etc --
        # those live on the real RemoteCapabilityRequest this envelope
        # merely references by id.
        self.assertNotIn("integrity_tag", cmd.payload)
        self.assertNotIn("relationship_id", cmd.payload)
        self.assertEqual(cmd.payload["fabric_request_id"], "CAPREQ-123")


if __name__ == "__main__":
    unittest.main()
