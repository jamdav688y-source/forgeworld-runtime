package substrate.core.repository

import substrate.core.model.AuditTrailEntry
import substrate.core.model.EvidenceRecord
import substrate.core.model.GraphEdge
import substrate.core.model.GraphNode
import substrate.core.model.MemoryRecord
import substrate.core.model.SyncQueueItem

/**
 * Storage seams. The Android `app` module implements each of these with Room;
 * `core` ships in-memory reference implementations so the pipeline is fully
 * testable on a plain JVM with no Android dependency.
 */
interface GraphRepository {
    fun getAllNodes(): List<GraphNode>
    fun getNode(id: String): GraphNode?
    fun upsertNode(node: GraphNode)
    fun getAllEdges(): List<GraphEdge>
    fun getEdgesForNode(nodeId: String): List<GraphEdge>
    fun upsertEdge(edge: GraphEdge)

    /** Records which node an event's content was bound to, so later events whose
     *  `dependsOnEventIds` reference it can resolve a DEPENDENCY edge target. */
    fun bindEventToNode(eventId: String, nodeId: String)
    fun getNodeIdForEvent(eventId: String): String?
}

interface MemoryRepository {
    fun getAllMemories(): List<MemoryRecord>
    fun getMemory(id: String): MemoryRecord?
    fun upsertMemory(memory: MemoryRecord)
}

interface EvidenceRepository {
    fun upsertEvidence(evidence: EvidenceRecord)
    fun getEvidenceForEvent(eventId: String): EvidenceRecord?
}

interface AuditTrailRepository {
    fun append(entry: AuditTrailEntry)
    fun getTrailForEvent(eventId: String): List<AuditTrailEntry>
}

interface SyncQueueRepository {
    fun enqueue(item: SyncQueueItem)
    fun pending(): List<SyncQueueItem>
    fun markSynced(id: String)
    fun markFailed(id: String)
}
