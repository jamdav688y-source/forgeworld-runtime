package substrate.core.pipeline

import substrate.core.model.EdgeType
import substrate.core.model.GraphEdge
import substrate.core.repository.GraphRepository

/**
 * Shared edge upsert used by both the expansion and reinforcement stages.
 * Edge ids are deterministic (`edge:<type>:<from>:<to>`) so repeated
 * co-activation strengthens one edge instead of spawning duplicates —
 * enforces the Resource Conservation Mandate's "no duplicate records".
 */
internal object GraphEdgeOps {
    fun reinforce(
        repo: GraphRepository,
        fromNodeId: String,
        toNodeId: String,
        type: EdgeType,
        weightDelta: Double,
        nowMillis: Long,
    ): GraphEdge {
        val id = "edge:$type:$fromNodeId:$toNodeId"
        val existing = repo.getAllEdges().firstOrNull { it.id == id }
        val updated = if (existing != null) {
            existing.copy(weight = existing.weight + weightDelta, lastReinforcedAtMillis = nowMillis)
        } else {
            GraphEdge(
                id = id,
                fromNodeId = fromNodeId,
                toNodeId = toNodeId,
                type = type,
                weight = weightDelta,
                lastReinforcedAtMillis = nowMillis,
            )
        }
        repo.upsertEdge(updated)
        return updated
    }

    fun slug(label: String): String =
        label.lowercase().trim().replace(Regex("[^a-z0-9]+"), "-").trim('-').ifBlank { "untitled" }
}
