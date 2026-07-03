package substrate.core.model

/**
 * A node in the weighted substrate graph. Every visual property the "neural
 * landscape" renders (brightness, radius, color, pulse) is derived from fields
 * on this record — Runtime Invariants #7/#8: visualizations are projections of
 * actual runtime state, never decoration.
 *
 * - `label` identifies the concept/topic this node represents (e.g. a project
 *   name, a recurring subject, or a domain anchor such as "GOVERNANCE").
 * - `importance` accumulates monotonically (reinforcement stage) and drives radius.
 * - `activation` decays over time from `lastActivatedAtMillis` and drives brightness.
 */
data class GraphNode(
    val id: String,
    val type: NodeType,
    val label: String,
    val importance: Double = 0.0,
    val activation: Double = 0.0,
    val lastActivatedAtMillis: Long = 0L,
    val createdAtMillis: Long,
)

/**
 * A weighted, directed relationship between two nodes. `weight` accumulates via
 * reinforcement (repeated co-activation); `lastReinforcedAtMillis` lets the
 * renderer show edge motion for recently active flows.
 */
data class GraphEdge(
    val id: String,
    val fromNodeId: String,
    val toNodeId: String,
    val type: EdgeType,
    val weight: Double = 1.0,
    val lastReinforcedAtMillis: Long,
)
