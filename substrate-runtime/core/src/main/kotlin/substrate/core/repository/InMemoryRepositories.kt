package substrate.core.repository

import java.util.concurrent.ConcurrentHashMap
import substrate.core.model.AuditTrailEntry
import substrate.core.model.EvidenceRecord
import substrate.core.model.GraphEdge
import substrate.core.model.GraphNode
import substrate.core.model.MemoryRecord
import substrate.core.model.SyncQueueItem
import substrate.core.model.SyncStatus

class InMemoryGraphRepository : GraphRepository {
    private val nodes = ConcurrentHashMap<String, GraphNode>()
    private val edges = ConcurrentHashMap<String, GraphEdge>()
    private val eventNodeBindings = ConcurrentHashMap<String, String>()

    override fun getAllNodes(): List<GraphNode> = nodes.values.toList()
    override fun getNode(id: String): GraphNode? = nodes[id]
    override fun upsertNode(node: GraphNode) { nodes[node.id] = node }
    override fun getAllEdges(): List<GraphEdge> = edges.values.toList()
    override fun getEdgesForNode(nodeId: String): List<GraphEdge> =
        edges.values.filter { it.fromNodeId == nodeId || it.toNodeId == nodeId }
    override fun upsertEdge(edge: GraphEdge) { edges[edge.id] = edge }
    override fun bindEventToNode(eventId: String, nodeId: String) { eventNodeBindings[eventId] = nodeId }
    override fun getNodeIdForEvent(eventId: String): String? = eventNodeBindings[eventId]
}

class InMemoryMemoryRepository : MemoryRepository {
    private val memories = ConcurrentHashMap<String, MemoryRecord>()

    override fun getAllMemories(): List<MemoryRecord> = memories.values.toList()
    override fun getMemory(id: String): MemoryRecord? = memories[id]
    override fun upsertMemory(memory: MemoryRecord) { memories[memory.id] = memory }
}

class InMemoryEvidenceRepository : EvidenceRepository {
    private val byEvent = ConcurrentHashMap<String, EvidenceRecord>()

    override fun upsertEvidence(evidence: EvidenceRecord) { byEvent[evidence.eventId] = evidence }
    override fun getEvidenceForEvent(eventId: String): EvidenceRecord? = byEvent[eventId]
}

class InMemoryAuditTrailRepository : AuditTrailRepository {
    private val entries = ConcurrentHashMap<String, MutableList<AuditTrailEntry>>()

    override fun append(entry: AuditTrailEntry) {
        entries.computeIfAbsent(entry.eventId) { mutableListOf() }.add(entry)
    }

    override fun getTrailForEvent(eventId: String): List<AuditTrailEntry> =
        entries[eventId]?.toList() ?: emptyList()
}

class InMemorySyncQueueRepository : SyncQueueRepository {
    private val items = ConcurrentHashMap<String, SyncQueueItem>()

    override fun enqueue(item: SyncQueueItem) { items[item.id] = item }
    override fun pending(): List<SyncQueueItem> = items.values.filter { it.status == SyncStatus.PENDING }
    override fun markSynced(id: String) {
        items[id]?.let { items[id] = it.copy(status = SyncStatus.SYNCED) }
    }
    override fun markFailed(id: String) {
        items[id]?.let { items[id] = it.copy(status = SyncStatus.FAILED, attempts = it.attempts + 1) }
    }
}
