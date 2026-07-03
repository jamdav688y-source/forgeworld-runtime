package substrate.core.model

/**
 * Heuristic commercial-opportunity scoring for an event. `score` is in [0,1];
 * `signals` lists the concrete evidence the score was built from so the
 * assessment is inspectable, not a black box.
 */
data class CommercialAssessment(
    val score: Double,
    val signals: List<String>,
    val rationale: String,
)
