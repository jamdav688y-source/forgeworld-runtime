package substrate.app.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
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

@Database(
    entities = [
        NodeEntity::class,
        EdgeEntity::class,
        EventNodeBindingEntity::class,
        MemoryEntity::class,
        EvidenceEntity::class,
        AuditEntity::class,
        SyncQueueEntity::class,
    ],
    version = 1,
    exportSchema = false,
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun nodeDao(): NodeDao
    abstract fun edgeDao(): EdgeDao
    abstract fun eventNodeBindingDao(): EventNodeBindingDao
    abstract fun memoryDao(): MemoryDao
    abstract fun evidenceDao(): EvidenceDao
    abstract fun auditDao(): AuditDao
    abstract fun syncQueueDao(): SyncQueueDao

    companion object {
        @Volatile private var instance: AppDatabase? = null

        fun getInstance(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "substrate.db",
                ).build().also { instance = it }
            }
    }
}
