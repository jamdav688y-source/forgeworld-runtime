package substrate.app.data.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "nodes")
data class NodeEntity(
    @PrimaryKey val id: String,
    val type: String,
    val label: String,
    val importance: Double,
    val activation: Double,
    val lastActivatedAtMillis: Long,
    val createdAtMillis: Long,
)

@Entity(tableName = "edges")
data class EdgeEntity(
    @PrimaryKey val id: String,
    val fromNodeId: String,
    val toNodeId: String,
    val type: String,
    val weight: Double,
    val lastReinforcedAtMillis: Long,
)

@Entity(tableName = "event_node_bindings")
data class EventNodeBindingEntity(
    @PrimaryKey val eventId: String,
    val nodeId: String,
)

@Entity(tableName = "memories")
data class MemoryEntity(
    @PrimaryKey val id: String,
    val eventId: String,
    val evidenceId: String,
    val nodeId: String,
    val summary: String,
    /** `key=value` pairs joined by `;` — see [substrate.app.data.repository.encodeVector]. */
    val vectorEncoded: String,
    val createdAtMillis: Long,
)

@Entity(tableName = "evidence")
data class EvidenceEntity(
    @PrimaryKey val id: String,
    val eventId: String,
    val description: String,
    val createdAtMillis: Long,
)

@Entity(tableName = "audit_trail")
data class AuditEntity(
    @PrimaryKey val id: String,
    val eventId: String,
    val stage: String,
    val summary: String,
    val timestampMillis: Long,
)

@Entity(tableName = "sync_queue")
data class SyncQueueEntity(
    @PrimaryKey val id: String,
    val eventId: String,
    val payload: String,
    val enqueuedAtMillis: Long,
    val status: String,
    val attempts: Int,
)
