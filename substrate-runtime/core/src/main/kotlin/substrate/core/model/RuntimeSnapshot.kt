package substrate.core.model

/**
 * A rendered node: activation has been decayed to "now" so brightness reflects
 * the true current state, not a stale write-time value.
 */
data class RenderedNode(
    val node: GraphNode,
    val currentActivation: Double,
)

/**
 * The single object the "neural landscape" UI is allowed to read from.
 * Runtime Invariants #7/#8: every visualization is generated from actual
 * runtime state, and none may exist without corresponding evidence — this
 * snapshot is built exclusively from repository-backed nodes/edges, never
 * from ad-hoc UI state.
 */
data class RuntimeSnapshot(
    val generatedAtMillis: Long,
    val nodes: List<RenderedNode>,
    val edges: List<GraphEdge>,
    val activityPulseFrequencyHz: Double,
)
