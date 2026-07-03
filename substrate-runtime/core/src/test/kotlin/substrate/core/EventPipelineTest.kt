package substrate.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import substrate.core.model.ExecutionDecisionKind
import substrate.core.orchestrator.EventPipeline
import substrate.core.pipeline.RuntimeSnapshotBuilder
import substrate.core.repository.InMemoryAuditTrailRepository
import substrate.core.repository.InMemoryEvidenceRepository
import substrate.core.repository.InMemoryGraphRepository
import substrate.core.repository.InMemoryMemoryRepository
import substrate.core.repository.InMemorySyncQueueRepository

class EventPipelineTest {

    private fun newPipeline(clock: LongArray): EventPipeline {
        val graph = InMemoryGraphRepository()
        val memory = InMemoryMemoryRepository()
        val evidence = InMemoryEvidenceRepository()
        val audit = InMemoryAuditTrailRepository()
        val sync = InMemorySyncQueueRepository()
        return EventPipeline(graph, memory, evidence, audit, sync) { clock[0] }
    }

    @Test
    fun `end-to-end run produces evidence, memory, graph edges, and a full audit trail`() {
        val clock = longArrayOf(1_000L)
        val graph = InMemoryGraphRepository()
        val memoryRepo = InMemoryMemoryRepository()
        val evidenceRepo = InMemoryEvidenceRepository()
        val auditRepo = InMemoryAuditTrailRepository()
        val syncRepo = InMemorySyncQueueRepository()
        val pipeline = EventPipeline(graph, memoryRepo, evidenceRepo, auditRepo, syncRepo) { clock[0] }

        val result = pipeline.submit(actor = "dave", text = "Client signed the contract, revenue opportunity confirmed #project:forgeworld")

        assertTrue(result.event.id.isNotBlank())
        assertNotNull(result.evidence)
        assertNotNull(result.memory)
        assertEquals(result.event.id, result.evidence!!.eventId)
        assertEquals(result.evidence!!.id, result.memory!!.evidenceId)
        assertTrue(result.newOrUpdatedEdgeIds.isNotEmpty())
        assertTrue(result.auditTrail.size >= 12, "expected all 12 pipeline stages to be logged, got ${result.auditTrail.map { it.stage }}")
        assertEquals(ExecutionDecisionKind.EXECUTE, result.executionOutcome.kind)

        // Every visualization must be a projection of actual runtime state.
        val snapshot = RuntimeSnapshotBuilder.build(graph, clock[0])
        assertTrue(snapshot.nodes.isNotEmpty())
        assertTrue(snapshot.nodes.any { it.node.id == "project:forgeworld" })
    }

    @Test
    fun `two events get two distinct ids`() {
        val clock = longArrayOf(1_000L)
        val pipeline = newPipeline(clock)
        val r1 = pipeline.submit(actor = "dave", text = "first event")
        val r2 = pipeline.submit(actor = "dave", text = "second event")
        assertNotEquals(r1.event.id, r2.event.id)
    }

    @Test
    fun `rejected event still produces evidence and memory, per the unconditional invariants`() {
        val clock = longArrayOf(1_000L)
        val pipeline = newPipeline(clock)
        val result = pipeline.submit(actor = "", text = "no actor, should be rejected")
        assertEquals(ExecutionDecisionKind.REJECT, result.executionOutcome.kind)
        assertNotNull(result.evidence, "Runtime Invariant #4: every event creates evidence, even a rejected one")
        assertNotNull(result.memory, "Runtime Invariant #6: every event becomes searchable memory, even a rejected one")
    }

    @Test
    fun `repeating the same event reinforces the existing edge instead of duplicating it`() {
        // Same actor + same text twice (e.g. a resync/retry) must land on the same
        // deterministic topic node id, so the PROJECT edge should be strengthened,
        // not duplicated. (Two *different* sentences about the same project are a
        // harder topic-clustering problem this implementation does not attempt —
        // see ARCHITECTURE_INDEX.md "Known simplifications".)
        val clock = longArrayOf(1_000L)
        val graph = InMemoryGraphRepository()
        val memoryRepo = InMemoryMemoryRepository()
        val evidenceRepo = InMemoryEvidenceRepository()
        val auditRepo = InMemoryAuditTrailRepository()
        val syncRepo = InMemorySyncQueueRepository()
        val pipeline = EventPipeline(graph, memoryRepo, evidenceRepo, auditRepo, syncRepo) { clock[0] }

        val text = "shipped the roadmap milestone #project:forgeworld"
        pipeline.submit(actor = "dave", text = text)
        clock[0] += 5_000L
        pipeline.submit(actor = "dave", text = text)

        val edgesToProject = graph.getEdgesForNode("project:forgeworld")
        val edgeIds = edgesToProject.map { it.id }.toSet()
        assertEquals(edgeIds.size, edgesToProject.size, "no duplicate edge ids should exist between the same node pair/type")
        val projectEdge = edgesToProject.first { it.type.name == "PROJECT" }
        assertTrue(projectEdge.weight > 1.0, "second activation should reinforce (increase) the existing edge's weight")
    }
}
