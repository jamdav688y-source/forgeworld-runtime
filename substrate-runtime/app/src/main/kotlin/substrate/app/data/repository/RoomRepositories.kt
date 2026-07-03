package substrate.app.data.repository

import substrate.app.data.dao.AuditDao
import substrate.app.data.dao.EdgeDao
import substrate.app.data.dao.EventNodeBindingDao
import substrate.app.data.dao.EvidenceDao
import substrate.app.data.dao.MemoryDao
import substrate.app.data.dao.NodeDao
import substrate.app.data.dao.SyncQueueDao
import substrate.app.data.entity.AuditEntity
import substrate.app.data.entity.EdgeEntity
import substrate.app.data.entity.EventNodeBindingEntity
import substrate.app.data.entity.EvidenceEntity
import substrate.app.data.entity.MemoryEntity
import substrate.app.data.entity.NodeEntity
import substrate.app.data.entity.SyncQueueEntity
import substrate.core.model.AuditTrailEntry
import substrate.core.model.EdgeType
import substrate.core.model.EvidenceRecord
import substrate.core.model.GraphEdge
import substrate.core.model.GraphNode
import substrate.core.model.MemoryRecord
import substrate.core.model.NodeType
import substrate.core.model.SyncQueueItem
import substrate.core.model.SyncStatus
import substrate.core.repository.AuditTrailRepository
import substrate.core.repository.EvidenceRepository
import substrate.core.repository.GraphRepository
import substrate.core.repository.MemoryRepository
import substrate.core.repository.SyncQueueRepository

/**
 * Room-backed implementations of the `core` repository interfaces. All methods
 * are blocking (matching `core`'s synchronous contracts) — call them from
 * `Dispatchers.IO` in ViewModels, never from the main thread.
 */
class RoomGraphRepository(
    private val nodeDao: NodeDao,
    private val edgeDao: EdgeDao,
    private val bindingDao: EventNodeBindingDao,
) : GraphRepository {

    override fun getAllNodes(): List<GraphNode> = nodeDao.getAll().map { it.toModel() }
    override fun getNode(id: String): GraphNode? = nodeDao.getById(id)?.toModel()
    override fun upsertNode(node: GraphNode) = nodeDao.upsert(node.toEntity())
    override fun getAllEdges(): List<GraphEdge> = edgeDao.getAll().map { it.toModel() }
    override fun getEdgesForNode(nodeId: String): List<GraphEdge> = edgeDao.getForNode(nodeId).map { it.toModel() }
    override fun upsertEdge(edge: GraphEdge) = edgeDao.upsert(edge.toEntity())
    override fun bindEventToNode(eventId: String, nodeId: String) =
        bindingDao.upsert(EventNodeBindingEntity(eventId, nodeId))
    override fun getNodeIdForEvent(eventId: String): String? = bindingDao.getNodeIdForEvent(eventId)
}

// Top-level (not private) so the reactive Compose ViewModels can reuse the same
// entity<->model mapping instead of re-deriving it.
internal fun NodeEntity.toModel() = GraphNode(
    id = id,
    type = NodeType.valueOf(type),
    label = label,
    importance = importance,
    activation = activation,
    lastActivatedAtMillis = lastActivatedAtMillis,
    createdAtMillis = createdAtMillis,
)

internal fun GraphNode.toEntity() = NodeEntity(
    id = id,
    type = type.name,
    label = label,
    importance = importance,
    activation = activation,
    lastActivatedAtMillis = lastActivatedAtMillis,
    createdAtMillis = createdAtMillis,
)

internal fun EdgeEntity.toModel() = GraphEdge(
    id = id,
    fromNodeId = fromNodeId,
    toNodeId = toNodeId,
    type = EdgeType.valueOf(type),
    weight = weight,
    lastReinforcedAtMillis = lastReinforcedAtMillis,
)

internal fun GraphEdge.toEntity() = EdgeEntity(
    id = id,
    fromNodeId = fromNodeId,
    toNodeId = toNodeId,
    type = type.name,
    weight = weight,
    lastReinforcedAtMillis = lastReinforcedAtMillis,
)

class RoomMemoryRepository(private val memoryDao: MemoryDao) : MemoryRepository {
    override fun getAllMemories(): List<MemoryRecord> = memoryDao.getAll().map { it.toModel() }
    override fun getMemory(id: String): MemoryRecord? = memoryDao.getById(id)?.toModel()
    override fun upsertMemory(memory: MemoryRecord) = memoryDao.upsert(memory.toEntity())

    private fun MemoryEntity.toModel() = MemoryRecord(
        id = id,
        eventId = eventId,
        evidenceId = evidenceId,
        nodeId = nodeId,
        summary = summary,
        vector = decodeVector(vectorEncoded),
        createdAtMillis = createdAtMillis,
    )

    private fun MemoryRecord.toEntity() = MemoryEntity(
        id = id,
        eventId = eventId,
        evidenceId = evidenceId,
        nodeId = nodeId,
        summary = summary,
        vectorEncoded = encodeVector(vector),
        createdAtMillis = createdAtMillis,
    )
}

class RoomEvidenceRepository(private val evidenceDao: EvidenceDao) : EvidenceRepository {
    override fun upsertEvidence(evidence: EvidenceRecord) = evidenceDao.upsert(
        EvidenceEntity(evidence.id, evidence.eventId, evidence.description, evidence.createdAtMillis),
    )
    override fun getEvidenceForEvent(eventId: String): EvidenceRecord? =
        evidenceDao.getForEvent(eventId)?.let { EvidenceRecord(it.id, it.eventId, it.description, it.createdAtMillis) }
}

class RoomAuditTrailRepository(private val auditDao: AuditDao) : AuditTrailRepository {
    override fun append(entry: AuditTrailEntry) = auditDao.insert(
        AuditEntity(entry.id, entry.eventId, entry.stage, entry.summary, entry.timestampMillis),
    )
    override fun getTrailForEvent(eventId: String): List<AuditTrailEntry> =
        auditDao.getForEvent(eventId).map { AuditTrailEntry(it.id, it.eventId, it.stage, it.summary, it.timestampMillis) }
}

class RoomSyncQueueRepository(private val syncQueueDao: SyncQueueDao) : SyncQueueRepository {
    override fun enqueue(item: SyncQueueItem) = syncQueueDao.upsert(
        SyncQueueEntity(item.id, item.eventId, item.payload, item.enqueuedAtMillis, item.status.name, item.attempts),
    )
    override fun pending(): List<SyncQueueItem> = syncQueueDao.getPending().map {
        SyncQueueItem(it.id, it.eventId, it.payload, it.enqueuedAtMillis, SyncStatus.valueOf(it.status), it.attempts)
    }
    override fun markSynced(id: String) = syncQueueDao.updateStatus(id, SyncStatus.SYNCED.name)
    override fun markFailed(id: String) = syncQueueDao.updateStatus(id, SyncStatus.FAILED.name)
}
