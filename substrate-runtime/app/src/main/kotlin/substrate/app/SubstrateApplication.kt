package substrate.app

import android.app.Application
import substrate.app.data.AppDatabase
import substrate.app.data.repository.RoomAuditTrailRepository
import substrate.app.data.repository.RoomEvidenceRepository
import substrate.app.data.repository.RoomGraphRepository
import substrate.app.data.repository.RoomMemoryRepository
import substrate.app.data.repository.RoomSyncQueueRepository
import substrate.core.orchestrator.EventPipeline

/**
 * Manual dependency wiring (no DI framework — the object graph is small enough
 * that Hilt/Koin would be pure ceremony). One [EventPipeline] instance backed
 * by Room, shared by every screen.
 */
class SubstrateApplication : Application() {

    lateinit var eventPipeline: EventPipeline
        private set

    lateinit var database: AppDatabase
        private set

    override fun onCreate() {
        super.onCreate()
        database = AppDatabase.getInstance(this)

        val graphRepository = RoomGraphRepository(database.nodeDao(), database.edgeDao(), database.eventNodeBindingDao())
        val memoryRepository = RoomMemoryRepository(database.memoryDao())
        val evidenceRepository = RoomEvidenceRepository(database.evidenceDao())
        val auditTrailRepository = RoomAuditTrailRepository(database.auditDao())
        val syncQueueRepository = RoomSyncQueueRepository(database.syncQueueDao())

        eventPipeline = EventPipeline(
            graphRepository = graphRepository,
            memoryRepository = memoryRepository,
            evidenceRepository = evidenceRepository,
            auditTrailRepository = auditTrailRepository,
            syncQueueRepository = syncQueueRepository,
        )
    }
}
