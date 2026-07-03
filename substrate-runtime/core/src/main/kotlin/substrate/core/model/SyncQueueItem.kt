package substrate.core.model

enum class SyncStatus { PENDING, SYNCED, FAILED }

/**
 * Offline-first sync unit. The substrate never blocks local operation on
 * network availability — items are enqueued locally and drained
 * opportunistically by whatever transport is wired in later (none is
 * implemented yet; see ARCHITECTURE_INDEX.md, "Synchronization — not yet wired").
 */
data class SyncQueueItem(
    val id: String,
    val eventId: String,
    val payload: String,
    val enqueuedAtMillis: Long,
    val status: SyncStatus = SyncStatus.PENDING,
    val attempts: Int = 0,
)
