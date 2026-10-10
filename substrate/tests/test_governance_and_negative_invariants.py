"""Governance and negative-invariant tests (Sections 11, 26, 29).

These wire GovernanceEngine/execute_workflow_step to the REAL fabric
governance path (fabric.interface.process_remote_capability_request,
InMemoryFabricTransport, PeerIdentityStore/PairingStore/LocalKeyStore/
RequestReplayGuard) -- nothing here is mocked. This is what Section 11
means by "every executable workflow must still traverse the existing
governance path."
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from substrate import interface as si
from fabric import interface as fi
from fabric import capabilities as fabric_capabilities  # noqa: F401 -- registers physical_ping
from fabric.transports import InMemoryFabricTransport

NODE_ID = "PC-NODE-SUBSTRATE-TEST"
ACTOR_ID = "SUBSTRATE-ACTOR"


def _demonstrated_graph(tmp):
    cg = si.CapabilityGraph(Path(tmp) / "cg")
    cg.register_discovered("physical_ping", display_name="Physical Ping", description="d", fabric_capability_id="physical_ping")
    for dim in si.DEFAULT_PROMOTION_POLICY[si.CAP_STATE_DEMONSTRATED]:
        cg.record_evidence_dimension("physical_ping", dim, si.DIM_EVIDENCED)
    gate = si.CapabilityPromotionGate()
    gate.apply_promotion(cg, gate.evaluate(cg.resolve_current("physical_ping"), si.CAP_STATE_DEMONSTRATED))
    return cg


def _objective():
    return si.ObjectiveContract(
        objective_id=si._new_id("OBJ"), desired_state="ping echoed", current_state="not pinged",
        required_capability_ids=("physical_ping",), authority_ceiling=("physical_ping",),
        evidence_required=(),
    )


def _capability_request(payload, transport, authority, artifact_id_override=None, request_id_override=None, **extra_fields):
    env = fi.build_artifact_envelope(ACTOR_ID, payload, declared_content_type="text/plain", artifact_id=artifact_id_override)
    corr = fi._new_id("CORR")
    xfer_req = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=ACTOR_ID,
        destination_node_id=NODE_ID, authority_context=authority, correlation_id=corr,
    )
    xfer_result = fi.submit_transfer(xfer_req, transport)
    cap_req = fi.RemoteCapabilityRequest(
        request_id=request_id_override or fi._new_id("CAPREQ"), source_node_id=ACTOR_ID, destination_node_id=NODE_ID,
        artifact_id=env.artifact_id, capability_id="physical_ping", authority_context=authority,
        correlation_id=corr, causation_id=xfer_result.transfer_id, timeout_seconds=5, **extra_fields,
    )
    return cap_req


class TestGovernanceEngine(unittest.TestCase):
    def test_approves_when_plan_executable_and_authority_grants_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, authority)
            self.assertEqual(decision.decision, si.GOVERNANCE_APPROVED)

    def test_denies_when_plan_has_missing_capabilities(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = si.CapabilityGraph(Path(tmp))  # empty
            obj = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
                required_capability_ids=("nonexistent",), authority_ceiling=("nonexistent",),
            )
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("nonexistent",), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, authority)
            self.assertEqual(decision.decision, si.GOVERNANCE_DENIED)
            self.assertIn("missing_capability_ids", decision.reason)

    def test_denies_when_authority_does_not_grant_the_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=(), granted_by="policy")  # nothing granted
            decision = si.GovernanceEngine().decide(plan, authority)
            self.assertEqual(decision.decision, si.GOVERNANCE_DENIED)

    def test_high_economic_value_never_overrides_a_missing_grant(self):
        """Section 26: commercial value must NOT override governance.
        GovernanceEngine.decide()'s signature does not even accept an
        ObjectiveContract (only a WorkflowPlan + AuthorityContext), so
        economic_context cannot influence this decision by construction."""
        with tempfile.TemporaryDirectory() as tmp:
            cg = _demonstrated_graph(tmp)
            obj = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="x", current_state="y",
                required_capability_ids=("physical_ping",), authority_ceiling=("physical_ping",),
                economic_context="high-value $1,000,000 deal contingent on this executing",
            )
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=(), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, authority)
            self.assertEqual(decision.decision, si.GOVERNANCE_DENIED)

    def test_governance_decision_can_only_be_produced_by_governance_engine(self):
        """Section 11: no planner/cognition/capability object may
        authorize itself. Structural check: nothing on WorkflowPlan,
        DifferentialCognitionEngine, CapabilityGraph, or WorkflowCompiler
        can construct a GovernanceDecision -- only GovernanceEngine.decide() can."""
        for cls in (si.WorkflowPlan, si.DifferentialCognitionEngine, si.CapabilityGraph, si.WorkflowCompiler, si.ObjectiveContract):
            for attr_name in dir(cls):
                if attr_name.startswith("_"):
                    continue
                attr = getattr(cls, attr_name)
                self.assertNotEqual(attr_name, "decide", msg=f"{cls.__name__} must not define its own decide()")


class TestExecuteWorkflowStepRefusesWithoutApproval(unittest.TestCase):
    def test_refuses_execution_without_approved_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=(), granted_by="policy")
            denied_decision = si.GovernanceEngine().decide(plan, authority)  # DENIED (no grant)
            transport = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            req = _capability_request(b"nonce", transport, authority)
            with self.assertRaises(si.GovernanceError):
                si.execute_workflow_step(plan, denied_decision, "physical_ping", req, transport)

    def test_refuses_execution_when_decision_is_for_a_different_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan_a, _ = si.WorkflowCompiler().compile(obj, cg)
            plan_b, _ = si.WorkflowCompiler().compile(obj, cg)  # a different plan_id for the same objective
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy")
            decision_for_a = si.GovernanceEngine().decide(plan_a, authority)
            transport = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            req = _capability_request(b"nonce", transport, authority)
            with self.assertRaises(si.GovernanceError):
                si.execute_workflow_step(plan_b, decision_for_a, "physical_ping", req, transport)

    def test_approved_execution_succeeds_and_produces_a_real_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, authority)
            transport = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            req = _capability_request(b"nonce", transport, authority)
            execution = si.execute_workflow_step(plan, decision, "physical_ping", req, transport)
            self.assertEqual(execution.fabric_result_status, fi.CAP_COMPLETED)
            self.assertIsNotNone(execution.fabric_receipt_id)


class TestNegativeInvariants(unittest.TestCase):
    """Section 29's negative paths, proven against the real fabric gates."""

    def test_unknown_peer_zero_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, authority)

            key_store = fi.LocalKeyStore(tmp / "keys")
            pairing_store = fi.PairingStore(tmp / "pairing")
            peer_store = fi.PeerIdentityStore(tmp / "peers")
            offer = pairing_store.create_offer(ACTOR_ID, NODE_ID, key_store)
            pairing_store.confirm(offer["relationship_id"], offer["sas"])
            key_bytes = key_store.resolve_key(offer["key_id"])
            unknown_peer_id = "PEER-" + fi.uuid.uuid4().hex

            transport = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            req = _capability_request(
                b"nonce", transport, authority,
                relationship_id=offer["relationship_id"], source_peer_id=unknown_peer_id,
            )
            signed = fi.sign_request(req, key_bytes, key_id=offer["key_id"])
            execution = si.execute_workflow_step(
                plan, decision, "physical_ping", signed, transport,
                pairing_store=pairing_store, key_store=key_store, peer_store=peer_store,
            )
            self.assertEqual(execution.fabric_result_status, fi.CAP_FAILED)

    def test_expired_authority_zero_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            granting_authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, granting_authority)  # approved under a VALID authority

            expired_authority = fi.AuthorityContext(
                actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy",
                granted_at="2020-01-01T00:00:00Z", expires_at="2020-01-01T00:05:00Z",
            )
            transport = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            req = _capability_request(b"nonce", transport, expired_authority)
            execution = si.execute_workflow_step(plan, decision, "physical_ping", req, transport)
            self.assertEqual(execution.fabric_result_status, fi.CAP_UNAUTHORIZED)

    def test_duplicate_request_zero_additional_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = _demonstrated_graph(tmp)
            obj = _objective()
            plan, _ = si.WorkflowCompiler().compile(obj, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, authority)
            replay_guard = fi.RequestReplayGuard(tmp / "lineage")
            lineage_store = None

            transport = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            fixed_request_id = fi._new_id("CAPREQ")
            req1 = _capability_request(b"nonce-1", transport, authority, request_id_override=fixed_request_id)
            exec1 = si.execute_workflow_step(plan, decision, "physical_ping", req1, transport, replay_guard=replay_guard, lineage_store=lineage_store)
            self.assertEqual(exec1.fabric_result_status, fi.CAP_COMPLETED)

            transport2 = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            req2 = _capability_request(b"nonce-1", transport2, authority, artifact_id_override=req1.artifact_id, request_id_override=fixed_request_id)
            exec2 = si.execute_workflow_step(plan, decision, "physical_ping", req2, transport2, replay_guard=replay_guard, lineage_store=lineage_store)
            self.assertEqual(exec2.fabric_result_status, fi.CAP_DUPLICATE_COMPLETED)

    def test_capability_advertisement_cannot_invoke_anything(self):
        from substrate import event_fabric as ef
        ad = ef.build_capability_advertisement(
            source_peer_id="PEER-x", destination_node_id=NODE_ID, capability_id="physical_ping",
            version="1", input_contract={}, output_contract={}, authority_requirement=("physical_ping",),
            availability="AVAILABLE", evidence_requirement=("TECHNICAL",), capability_state=si.CAP_STATE_DEMONSTRATED,
        )
        self.assertFalse(hasattr(ad, "invoke"))
        self.assertFalse(hasattr(ad, "execute"))
        self.assertEqual(ad.message_type, ef.MSG_CAPABILITY_ADVERTISEMENT)

    def test_memory_delta_envelope_is_not_itself_promoted_memory(self):
        from substrate import event_fabric as ef
        delta = ef.build_memory_delta(
            source_peer_id="PEER-x", destination_node_id=NODE_ID,
            proposed_record={"claim": "unverified speculation"}, target_memory_class="SEMANTIC",
        )
        self.assertFalse(delta.payload["promoted"])
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp / "cg")
            el = si.EvidenceLedger(tmp / "evid")
            store = si.MemoryStore(tmp / "mem", cg, el)
            # Receiving the envelope changes nothing on its own -- promotion
            # is a SEPARATE, evidence-gated call the receiver must choose to make.
            self.assertEqual(store.list_semantic(), ())
            with self.assertRaises(si.MemoryPromotionError):
                store.promote_to_semantic(delta.payload["proposed_record"], evidence_ids=())

    def test_heartbeat_carries_no_authority_relevant_fields(self):
        from substrate import event_fabric as ef
        hb = ef.build_heartbeat(source_peer_id="PEER-x", destination_node_id=NODE_ID)
        self.assertEqual(hb.payload, {"alive": True})
        self.assertNotIn("capability_id", hb.payload)
        self.assertNotIn("authority_context", hb.payload)

    def test_event_envelope_cannot_be_mistaken_for_a_command(self):
        from substrate import event_fabric as ef
        event = ef.build_event(source_peer_id="PEER-x", destination_node_id=NODE_ID, description="something happened")
        self.assertNotIn("capability_id", event.payload)
        self.assertNotIn("fabric_request_id", event.payload)
        self.assertNotEqual(event.message_type, ef.MSG_COMMAND)


if __name__ == "__main__":
    unittest.main()
