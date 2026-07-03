package substrate.core.model

/**
 * Searchable memory derived from an event (Runtime Invariant #6). Every memory
 * must reference the evidence it was built from (Constitution v3 Core Law:
 * "Evidence precedes memory") — `evidenceId` is non-null and enforced by
 * [substrate.core.pipeline.EvidenceRecorder] running before memory is written.
 */
data class MemoryRecord(
    val id: String,
    val eventId: String,
    val evidenceId: String,
    val nodeId: String,
    val summary: String,
    val vector: Map<String, Double>,
    val createdAtMillis: Long,
)

/** Evidence is recorded for every event before it may become memory (Core Law 1). */
data class EvidenceRecord(
    val id: String,
    val eventId: String,
    val description: String,
    val createdAtMillis: Long,
)
