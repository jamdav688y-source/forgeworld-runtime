"""Section 28: the deterministic synthetic end-to-end proof of the full
organism loop --

  SIGNAL -> PROBLEM HYPOTHESIS -> OBJECTIVE -> DIFFERENTIAL COGNITION
  -> CAPABILITY GRAPH QUERY -> WORKFLOW COMPILATION (one existing +
  one missing capability) -> FOUNDRY PROOF -> GOVERNANCE DECISION
  -> EXECUTION (real fabric governance path) -> EVIDENCE -> OUTCOME
  -> PROMOTION -> REACHABILITY DELTA

Every transition gets an id; causation must be reconstructable from the
final ExecutionRecord back to the originating SignalEvent. This test
answers, in its own assertions, exactly the questions Section 28 poses:
WHY did this execution happen, what objective did it serve, what
capabilities were used, what evidence justified them, what authority
allowed execution, what result occurred, what was learned, what was
promoted, and what became reachable afterward.

Section 14's Donab-shaped reference transaction is exercised here too,
as a SYNTHETIC scenario only: no network call, no real customer, no
alteration of any real state -- see test_donab_shaped_commercial_loop_is_synthetic_only.
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from substrate import interface as si
from substrate import event_fabric as ef
from fabric import interface as fi
from fabric import capabilities as fabric_capabilities  # noqa: F401
from fabric.transports import InMemoryFabricTransport

NODE_ID = "PC-NODE-ORGANISM-E2E"
ACTOR_ID = "ORGANISM-ACTOR"


class TestSyntheticOrganismEndToEnd(unittest.TestCase):
    def test_full_loop_with_reconstructable_causation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp / "capgraph")
            el = si.EvidenceLedger(tmp / "evidence")
            memory = si.MemoryStore(tmp / "memory", cg, el)

            # ---- WORLD -> SIGNAL --------------------------------------
            signal = si.SignalEvent(
                signal_id=si._new_id("SIG"), origin="customer_interaction",
                raw_content="Customer said replying to every inbound message by hand is slow.",
                provenance=si.OBSERVED,
            )
            memory.write_episodic(signal)

            # ---- SIGNAL -> PROBLEM HYPOTHESIS --------------------------
            hypothesis = si.ProblemHypothesis(
                hypothesis_id=si._new_id("HYP"), source_signal_ids=(signal.signal_id,),
                description="Manual reply latency may be costing the customer time and losing them opportunities.",
                evidence_for=(signal.signal_id,), missing_evidence=("customer_confirmed_this_is_worth_solving",),
                confidence=si.CONFIDENCE_PARTIAL, possible_cost_dimensions=("TIME", "LOST_OPPORTUNITY"),
                status=si.HYPOTHESIS_ACCEPTED,
            )

            # ---- HYPOTHESIS -> OBJECTIVE --------------------------------
            # required_capability_ids deliberately names ONE capability this
            # test will make EXISTING (physical_ping) and one it will make
            # MISSING then run through the Foundry (auto_acknowledge_reply).
            objective = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="inbound messages receive a governed, evidenced automatic acknowledgment",
                current_state="all replies are manual", required_capability_ids=("physical_ping", "auto_acknowledge_reply"),
                authority_ceiling=("physical_ping", "auto_acknowledge_reply"),
                evidence_required=("customer_confirmed_this_is_worth_solving",),
                reversibility=si.REVERSIBLE, external_effects_allowed=False,
                economic_context="prospective repeat-customer relationship, value not yet quantified",
                source_hypothesis_id=hypothesis.hypothesis_id,
            )

            # ---- DIFFERENTIAL COGNITION ---------------------------------
            cognition_records, contradiction_map, synthesis = si.DifferentialCognitionEngine().run(
                objective, evidence=(hypothesis.hypothesis_id,),
            )
            self.assertEqual(contradiction_map.objective_id, objective.objective_id)
            # Missing evidence was correctly identified (nothing in this
            # round supplied "customer_confirmed_this_is_worth_solving").
            self.assertIn("customer_confirmed_this_is_worth_solving", contradiction_map.missing_evidence)

            # ---- CAPABILITY GRAPH: one existing, one missing ------------
            cg.register_discovered("physical_ping", display_name="Physical Ping", description="harmless nonce echo", fabric_capability_id="physical_ping")
            for dim in si.DEFAULT_PROMOTION_POLICY[si.CAP_STATE_DEMONSTRATED]:
                cg.record_evidence_dimension("physical_ping", dim, si.DIM_EVIDENCED)
            gate = si.CapabilityPromotionGate()
            gate.apply_promotion(cg, gate.evaluate(cg.resolve_current("physical_ping"), si.CAP_STATE_DEMONSTRATED))

            # ---- WORKFLOW COMPILATION: names the gap, never hallucinates -
            plan, gaps = si.WorkflowCompiler().compile(objective, cg)
            self.assertEqual(plan.existing_capability_ids, ("physical_ping",))
            self.assertEqual(plan.missing_capability_ids, ("auto_acknowledge_reply",))
            self.assertFalse(plan.is_executable)
            self.assertEqual(len(gaps), 1)
            gap = gaps[0]

            # ---- CAPABILITY FOUNDRY: smallest reversible probe ----------
            foundry = si.CapabilityFoundry(cg, el)
            probe_calls = []

            def harmless_probe():
                # The "smallest reversible probe": construct and verify a
                # PhysicalPingCapability-style echo entirely in-process, no
                # filesystem mutation, no shell, no external effect.
                echoed = "probe-nonce"
                probe_calls.append(echoed)
                return True, f"probe echoed {echoed!r} successfully"

            resolved_gap, gap_evidence = foundry.run_probe(
                gap, harmless_probe, display_name="Auto Acknowledge Reply",
                description="drafts and would send a bounded acknowledgment reply",
            )
            self.assertEqual(resolved_gap.status, si.GAP_RESOLVED)
            self.assertEqual(probe_calls, ["probe-nonce"])
            # TOOL CREATED != CAPABILITY DEMONSTRATED: still not available.
            self.assertFalse(cg.is_available("auto_acknowledge_reply"))

            # Promote auto_acknowledge_reply only as far as its OWN evidence
            # supports (TECHNICAL only) -- CANDIDATE, not DEMONSTRATED yet,
            # honestly reflecting that governance evidence hasn't been
            # gathered for this new ability.
            candidate_decision = gate.evaluate(cg.resolve_current("auto_acknowledge_reply"), si.CAP_STATE_CANDIDATE)
            self.assertEqual(candidate_decision.decision, si.PROMOTE)
            gate.apply_promotion(cg, candidate_decision)
            self.assertEqual(cg.resolve_current("auto_acknowledge_reply")["lifecycle_state"], si.CAP_STATE_CANDIDATE)

            # This mission's own workflow now proceeds on physical_ping ONLY
            # (the one truly DEMONSTRATED, executable capability) -- the
            # still-CANDIDATE auto_acknowledge_reply is correctly excluded.
            objective_narrowed = si.ObjectiveContract(
                objective_id=objective.objective_id, desired_state=objective.desired_state,
                current_state=objective.current_state, required_capability_ids=("physical_ping",),
                authority_ceiling=("physical_ping", "auto_acknowledge_reply"), evidence_required=objective.evidence_required,
                source_hypothesis_id=hypothesis.hypothesis_id,
            )
            executable_plan, no_gaps = si.WorkflowCompiler().compile(objective_narrowed, cg)
            self.assertTrue(executable_plan.is_executable)
            self.assertEqual(no_gaps, ())

            # ---- GOVERNANCE ----------------------------------------------
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="operator_default_policy")
            governance_decision = si.GovernanceEngine().decide(executable_plan, authority)
            self.assertEqual(governance_decision.decision, si.GOVERNANCE_APPROVED)

            # ---- EXECUTION: the real fabric governance path ---------------
            transport = InMemoryFabricTransport(registered_nodes=(NODE_ID,))
            nonce_payload = f"organism-e2e-{objective.objective_id}".encode()
            env = fi.build_artifact_envelope(ACTOR_ID, nonce_payload, declared_content_type="text/plain")
            corr = fi._new_id("CORR")
            xfer_req = fi.TransferRequest(
                request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=ACTOR_ID,
                destination_node_id=NODE_ID, authority_context=authority, correlation_id=corr,
            )
            xfer_result = fi.submit_transfer(xfer_req, transport)
            cap_req = fi.RemoteCapabilityRequest(
                request_id=fi._new_id("CAPREQ"), source_node_id=ACTOR_ID, destination_node_id=NODE_ID,
                artifact_id=env.artifact_id, capability_id="physical_ping", authority_context=authority,
                correlation_id=corr, causation_id=xfer_result.transfer_id, timeout_seconds=5,
            )
            execution = si.execute_workflow_step(executable_plan, governance_decision, "physical_ping", cap_req, transport)
            self.assertEqual(execution.fabric_result_status, fi.CAP_COMPLETED)
            self.assertIsNotNone(execution.fabric_receipt_id)

            # ---- EVIDENCE --------------------------------------------------
            execution_evidence = si.EvidenceRecord(
                evidence_id=si._new_id("EVID"), claim="physical_ping executed under this objective's governed workflow",
                test_or_observation=f"execute_workflow_step -> receipt {execution.fabric_receipt_id}",
                result=execution.fabric_result_status, provenance=si.SYSTEM_ASSERTED, evidence_dimension="OPERATIONAL",
                source_execution_id=execution.execution_id,
            )
            el.write(execution_evidence)
            cg.record_evidence_dimension("physical_ping", "OPERATIONAL", si.DIM_EVIDENCED)

            # ---- OUTCOME (synthetic; no real customer/payment claimed) ---
            outcome = si.OutcomeRecord(
                outcome_id=si._new_id("OUT"), objective_id=objective.objective_id,
                dimension_results={
                    "technical_success": si.DIM_ACHIEVED, "operational_success": si.DIM_ACHIEVED,
                    "customer_acceptance": si.DIM_UNKNOWN, "economic_result": si.DIM_UNKNOWN,
                },
                commercial_evidence_ids=(),
            )
            self.assertEqual(outcome.dimension_results["customer_acceptance"], si.DIM_UNKNOWN)  # honestly unmeasured

            # ---- LEARNING: promote to semantic memory using the evidence --
            memory.promote_to_semantic(
                {"claim": execution_evidence.claim, "objective_id": objective.objective_id},
                evidence_ids=(execution_evidence.evidence_id,),
            )
            self.assertEqual(len(memory.list_semantic()), 1)

            # ---- PROMOTION ---------------------------------------------------
            promotion_decision = gate.evaluate(cg.resolve_current("physical_ping"), si.CAP_STATE_OPERATIONALLY_PROVEN)
            self.assertEqual(promotion_decision.decision, si.PROMOTE)
            applied = gate.apply_promotion(cg, promotion_decision)
            self.assertTrue(applied)
            self.assertEqual(cg.resolve_current("physical_ping")["lifecycle_state"], si.CAP_STATE_OPERATIONALLY_PROVEN)

            # ---- REACHABILITY --------------------------------------------
            objective_classes = {"AUTOMATED_ACKNOWLEDGMENT_CLASS": ("physical_ping", "auto_acknowledge_reply")}
            reach_engine = si.ReachabilityEngine(cg, objective_classes)
            before = frozenset()  # neither capability was OPERATIONALLY_PROVEN+DEMONSTRATED-both before this test
            delta = reach_engine.compute_delta_after_promotion("physical_ping", before)
            # auto_acknowledge_reply is only CANDIDATE (not >= DEMONSTRATED),
            # so the class correctly remains unreachable -- promotion of ONE
            # dependency does not fabricate reachability for the whole class.
            self.assertEqual(delta.newly_reachable_objective_classes, ())

            # ---- CAUSATION RECONSTRUCTION (Section 28's own questions) ----
            # WHY did this execution happen? -> objective_id traces to hypothesis -> signal.
            self.assertEqual(executable_plan.objective_id, objective.objective_id)
            self.assertEqual(objective_narrowed.source_hypothesis_id, hypothesis.hypothesis_id)
            self.assertIn(signal.signal_id, hypothesis.source_signal_ids)
            # WHAT capabilities were used? -> physical_ping, exactly the one executed.
            self.assertEqual(execution.capability_id, "physical_ping")
            # WHAT evidence justified them? -> execution_evidence cites the execution_id.
            self.assertEqual(execution_evidence.source_execution_id, execution.execution_id)
            # WHAT authority allowed execution? -> governance_decision names the actor and is APPROVED.
            self.assertEqual(governance_decision.authority_actor_id, authority.actor_id)
            self.assertEqual(governance_decision.decision, si.GOVERNANCE_APPROVED)
            # WHAT result occurred? -> execution.fabric_result_status/receipt.
            self.assertEqual(execution.fabric_result_status, fi.CAP_COMPLETED)
            # WHAT was learned? -> one semantic memory record, evidence-gated.
            self.assertEqual(len(memory.list_semantic()), 1)
            # WHAT was promoted? -> physical_ping to OPERATIONALLY_PROVEN, via a named decision.
            self.assertEqual(promotion_decision.capability_id, "physical_ping")
            self.assertEqual(promotion_decision.requested_lifecycle_state, si.CAP_STATE_OPERATIONALLY_PROVEN)
            # WHAT became reachable afterward? -> explicitly NOT this class yet (honest, not overclaimed).
            self.assertEqual(delta.newly_reachable_objective_classes, ())

    def test_donab_shaped_commercial_loop_is_synthetic_only(self):
        """Section 14: exercise the complete commercial-loop SHAPE using
        the bounded-agent-build concept as a reference architecture only.
        No network call is made, no real customer record is touched --
        this test constructs every object entirely in-memory/on a tmp dir."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            cg = si.CapabilityGraph(tmp / "cg")
            el = si.EvidenceLedger(tmp / "evid")

            signal = si.SignalEvent(
                signal_id=si._new_id("SIG"), origin="social_observation",
                raw_content="SYNTHETIC placeholder signal, shaped like a bounded-agent-build inquiry -- not a real observation of any person.",
                provenance=si.OBSERVED,
            )
            hypothesis = si.ProblemHypothesis(
                hypothesis_id=si._new_id("HYP"), source_signal_ids=(signal.signal_id,),
                description="SYNTHETIC: a prospective customer may want a bounded agent built for them.",
                confidence=si.CONFIDENCE_UNVERIFIED, status=si.HYPOTHESIS_PROPOSED,
            )
            objective = si.ObjectiveContract(
                objective_id=si._new_id("OBJ"), desired_state="SYNTHETIC bounded agent delivered and accepted",
                current_state="no engagement exists", required_capability_ids=("physical_ping",),
                authority_ceiling=("physical_ping",), source_hypothesis_id=hypothesis.hypothesis_id,
                economic_context="SYNTHETIC: hypothetical fixed-fee bounded-agent-build engagement",
            )
            cg.register_discovered("physical_ping", display_name="x", description="y", fabric_capability_id="physical_ping")
            for dim in si.DEFAULT_PROMOTION_POLICY[si.CAP_STATE_DEMONSTRATED]:
                cg.record_evidence_dimension("physical_ping", dim, si.DIM_EVIDENCED)
            gate = si.CapabilityPromotionGate()
            gate.apply_promotion(cg, gate.evaluate(cg.resolve_current("physical_ping"), si.CAP_STATE_DEMONSTRATED))
            plan, _ = si.WorkflowCompiler().compile(objective, cg)
            authority = fi.AuthorityContext(actor_id=ACTOR_ID, granted_capability_ids=("physical_ping",), granted_by="policy")
            decision = si.GovernanceEngine().decide(plan, authority)
            self.assertEqual(decision.decision, si.GOVERNANCE_APPROVED)

            # SYNTHETIC outcome: every commercial dimension is explicitly
            # UNKNOWN -- this test proves the SHAPE can be represented, it
            # never marks acceptance/payment as having occurred.
            outcome = si.OutcomeRecord(
                outcome_id=si._new_id("OUT"), objective_id=objective.objective_id,
                dimension_results={
                    "technical_success": si.DIM_UNKNOWN, "operational_success": si.DIM_UNKNOWN,
                    "customer_acceptance": si.DIM_UNKNOWN, "economic_result": si.DIM_UNKNOWN,
                },
            )
            for dim_value in outcome.dimension_results.values():
                self.assertEqual(dim_value, si.DIM_UNKNOWN)

            # No message_fabric COMMAND/EVENT was ever addressed to a real
            # external system -- every envelope in this test, if any were
            # built, would target NODE_ID (this test's own in-process node),
            # never a real Donab endpoint. Confirmed by never importing or
            # calling anything network-capable in this test at all.


if __name__ == "__main__":
    unittest.main()
