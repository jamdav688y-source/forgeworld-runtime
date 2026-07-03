package substrate.core.pipeline

/** Canonical stage names used in [substrate.core.model.AuditTrailEntry.stage]. */
object PipelineStage {
    const val CAPTURE = "CAPTURE"
    const val NORMALIZE = "NORMALIZE"
    const val CLASSIFY = "CLASSIFY"
    const val ACTIVATION_PULSE = "ACTIVATION_PULSE"
    const val MEMORY_RETRIEVAL = "MEMORY_RETRIEVAL"
    const val RELATIONSHIP_EXPANSION = "RELATIONSHIP_EXPANSION"
    const val GOVERNANCE_VALIDATION = "GOVERNANCE_VALIDATION"
    const val COMMERCIAL_ANALYSIS = "COMMERCIAL_ANALYSIS"
    const val EXECUTION_DECISION = "EXECUTION_DECISION"
    const val EVIDENCE_RECORDING = "EVIDENCE_RECORDING"
    const val RELATIONSHIP_REINFORCEMENT = "RELATIONSHIP_REINFORCEMENT"
    const val RUNTIME_SNAPSHOT = "RUNTIME_SNAPSHOT"
}
