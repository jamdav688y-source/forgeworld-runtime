package substrate.app.data.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow
import substrate.app.data.entity.AuditEntity
import substrate.app.data.entity.EdgeEntity
import substrate.app.data.entity.EventNodeBindingEntity
import substrate.app.data.entity.EvidenceEntity
import substrate.app.data.entity.MemoryEntity
import substrate.app.data.entity.NodeEntity
import substrate.app.data.entity.SyncQueueEntity

/**
 * DAO methods used by the [substrate.core.repository] implementations are plain
 * (blocking) calls, matching `core`'s synchronous repository interfaces — callers
 * are expected to invoke them from a background dispatcher (see the ViewModels
 * in `ui/`). The `Flow`-returning queries are additional, separate methods used
 * only for reactive Compose UI observation (the neural landscape, audit screen).
 */
@Dao
interface NodeDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun upsert(node: NodeEntity)

    @Query("SELECT * FROM nodes")
    fun getAll(): List<NodeEntity>

    @Query("SELECT * FROM nodes WHERE id = :id")
    fun getById(id: String): NodeEntity?

    @Query("SELECT * FROM nodes")
    fun observeAll(): Flow<List<NodeEntity>>
}

@Dao
interface EdgeDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun upsert(edge: EdgeEntity)

    @Query("SELECT * FROM edges")
    fun getAll(): List<EdgeEntity>

    @Query("SELECT * FROM edges WHERE fromNodeId = :nodeId OR toNodeId = :nodeId")
    fun getForNode(nodeId: String): List<EdgeEntity>

    @Query("SELECT * FROM edges")
    fun observeAll(): Flow<List<EdgeEntity>>
}

@Dao
interface EventNodeBindingDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun upsert(binding: EventNodeBindingEntity)

    @Query("SELECT nodeId FROM event_node_bindings WHERE eventId = :eventId")
    fun getNodeIdForEvent(eventId: String): String?
}

@Dao
interface MemoryDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun upsert(memory: MemoryEntity)

    @Query("SELECT * FROM memories")
    fun getAll(): List<MemoryEntity>

    @Query("SELECT * FROM memories WHERE id = :id")
    fun getById(id: String): MemoryEntity?
}

@Dao
interface EvidenceDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun upsert(evidence: EvidenceEntity)

    @Query("SELECT * FROM evidence WHERE eventId = :eventId")
    fun getForEvent(eventId: String): EvidenceEntity?
}

@Dao
interface AuditDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun insert(entry: AuditEntity)

    @Query("SELECT * FROM audit_trail WHERE eventId = :eventId ORDER BY timestampMillis ASC")
    fun getForEvent(eventId: String): List<AuditEntity>

    @Query("SELECT * FROM audit_trail ORDER BY timestampMillis DESC LIMIT 200")
    fun observeRecent(): Flow<List<AuditEntity>>
}

@Dao
interface SyncQueueDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    fun upsert(item: SyncQueueEntity)

    @Query("SELECT * FROM sync_queue WHERE status = 'PENDING'")
    fun getPending(): List<SyncQueueEntity>

    @Query("UPDATE sync_queue SET status = :status, attempts = attempts + CASE WHEN :status = 'FAILED' THEN 1 ELSE 0 END WHERE id = :id")
    fun updateStatus(id: String, status: String)
}
