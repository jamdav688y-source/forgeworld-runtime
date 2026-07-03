package substrate.core.model

/**
 * One inspectable step in an event's journey through the pipeline. The
 * Observability requirement ("no hidden reasoning without an observable audit
 * trail") is satisfied by every pipeline stage appending exactly one of these.
 */
data class AuditTrailEntry(
    val id: String,
    val eventId: String,
    val stage: String,
    val summary: String,
    val timestampMillis: Long,
)

/**
 * Full record of a single event's run through the substrate, aggregating every
 * stage's output. This — not any UI state — is the single source of truth the
 * "neural landscape" and audit screens read from.
 */
data class PipelineResult(
    val event: Event,
    val normalized: NormalizedEvent,
    val classification: Classification,
    val activatedNodeIds: List<String>,
    val retrievedMemoryIds: List<String>,
    val newOrUpdatedEdgeIds: List<String>,
    val governanceDecision: GovernanceDecision,
    val commercialAssessment: CommercialAssessment,
    val executionOutcome: ExecutionOutcome,
    val evidence: EvidenceRecord?,
    val memory: MemoryRecord?,
    val auditTrail: List<AuditTrailEntry>,
)
