package substrate.core.pipeline

import substrate.core.model.RenderedNode
import substrate.core.model.RuntimeSnapshot
import substrate.core.repository.GraphRepository

/**
 * Stage 12: Render Updated Neural Landscape. Does not draw anything itself —
 * `app`'s Compose Canvas layer is the renderer. This builder's job is to
 * produce the one legitimate data source that renderer may read: decayed
 * activations computed fresh at snapshot time, plus the current edge set.
 */
object RuntimeSnapshotBuilder {
    fun build(repo: GraphRepository, nowMillis: Long): RuntimeSnapshot {
        val nodes = repo.getAllNodes().map { node ->
            RenderedNode(node = node, currentActivation = ActivationPulseGenerator.decayedActivation(node, nowMillis))
        }
        val edges = repo.getAllEdges()

        val recentlyActive = nodes.count { it.node.lastActivatedAtMillis > 0 && nowMillis - it.node.lastActivatedAtMillis <= 60_000 }
        // Pulse frequency is a direct function of how many nodes fired in the last minute —
        // not a decorative animation constant.
        val frequencyHz = (recentlyActive.toDouble() / 60.0).coerceAtLeast(0.0)

        return RuntimeSnapshot(
            generatedAtMillis = nowMillis,
            nodes = nodes,
            edges = edges,
            activityPulseFrequencyHz = frequencyHz,
        )
    }
}
