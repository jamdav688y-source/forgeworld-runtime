package substrate.core.pipeline

import substrate.core.model.Classification
import substrate.core.model.EdgeType
import substrate.core.model.GraphNode
import substrate.core.model.MemoryRecord
import substrate.core.model.NodeType
import substrate.core.model.NormalizedEvent
import substrate.core.repository.GraphRepository

data class ExpansionResult(
    val topicNodeId: String,
    val activatedNodeIds: List<String>,
    val touchedEdgeIds: List<String>,
)

/**
 * Stage 6: Compute Relationship Expansion. Runtime Invariant #5 — every event
 * updates the relationship graph. Materializes/reinforces SEMANTIC, TEMPORAL,
 * PROJECT, USER, RUNTIME, and DEPENDENCY edges (EVIDENCE is added later, in
 * [RelationshipReinforcer], once evidence actually exists).
 */
class RelationshipGraphEngine(private val repo: GraphRepository) {

    private val recentWindowMillis = 30L * 60 * 1000 // 30 minutes, for TEMPORAL edges

    fun expand(
        normalized: NormalizedEvent,
        classification: Classification,
        relatedMemories: List<Pair<MemoryRecord, Double>>,
        nowMillis: Long,
    ): ExpansionResult {
        val activated = mutableListOf<String>()
        val edges = mutableListOf<String>()

        val domainNode = ensureDomainAnchor(classification.primaryType, nowMillis)
        activated += domainNode.id

        val topicLabel = topicLabelFor(normalized)
        val topicNode = ensureAndPulse(
            id = "topic:${GraphEdgeOps.slug(topicLabel)}",
            type = classification.primaryType,
            label = topicLabel,
            nowMillis = nowMillis,
        )
        activated += topicNode.id
        edges += GraphEdgeOps.reinforce(repo, topicNode.id, domainNode.id, EdgeType.RUNTIME, 1.0, nowMillis).id

        val actorNode = ensureAndPulse(
            id = "user:${GraphEdgeOps.slug(normalized.source.actor)}",
            type = NodeType.OBSERVATION,
            label = normalized.source.actor,
            nowMillis = nowMillis,
        )
        activated += actorNode.id
        edges += GraphEdgeOps.reinforce(repo, topicNode.id, actorNode.id, EdgeType.USER, 1.0, nowMillis).id

        val runtimeAnchor = ensureDomainAnchor(NodeType.RUNTIME, nowMillis)
        activated += runtimeAnchor.id
        edges += GraphEdgeOps.reinforce(repo, topicNode.id, runtimeAnchor.id, EdgeType.RUNTIME, 0.25, nowMillis).id

        relatedMemories.forEach { (memory, similarity) ->
            edges += GraphEdgeOps.reinforce(repo, topicNode.id, memory.nodeId, EdgeType.SEMANTIC, similarity, nowMillis).id
            activated += memory.nodeId
        }

        repo.getAllNodes()
            .filter { it.id != topicNode.id && it.lastActivatedAtMillis > 0 }
            .filter { nowMillis - it.lastActivatedAtMillis <= recentWindowMillis }
            .sortedByDescending { it.lastActivatedAtMillis }
            .take(3)
            .forEach { recent ->
                edges += GraphEdgeOps.reinforce(repo, topicNode.id, recent.id, EdgeType.TEMPORAL, 0.5, nowMillis).id
                activated += recent.id
            }

        normalized.extractedTags
            .filter { it.startsWith("project:") }
            .map { it.removePrefix("project:") }
            .forEach { projectLabel ->
                val projectNode = ensureAndPulse(
                    id = "project:${GraphEdgeOps.slug(projectLabel)}",
                    type = NodeType.PROJECTS,
                    label = projectLabel,
                    nowMillis = nowMillis,
                )
                activated += projectNode.id
                edges += GraphEdgeOps.reinforce(repo, topicNode.id, projectNode.id, EdgeType.PROJECT, 1.0, nowMillis).id
            }

        normalized.source.dependsOnEventIds.forEach { depEventId ->
            val depNodeId = repo.getNodeIdForEvent(depEventId) ?: return@forEach
            edges += GraphEdgeOps.reinforce(repo, topicNode.id, depNodeId, EdgeType.DEPENDENCY, 1.0, nowMillis).id
            activated += depNodeId
        }

        repo.bindEventToNode(normalized.source.id, topicNode.id)

        return ExpansionResult(
            topicNodeId = topicNode.id,
            activatedNodeIds = activated.distinct(),
            touchedEdgeIds = edges.distinct(),
        )
    }

    private fun topicLabelFor(normalized: NormalizedEvent): String {
        val firstTag = normalized.extractedTags.firstOrNull { !it.startsWith("project:") }
        if (firstTag != null) return firstTag.trimStart('#', '@')
        val words = normalized.cleanedText.split(" ").filter { it.isNotBlank() }
        return if (words.isEmpty()) "observation" else words.take(6).joinToString(" ")
    }

    private fun ensureDomainAnchor(type: NodeType, nowMillis: Long): GraphNode =
        ensureAndPulse(id = "domain:$type", type = type, label = type.name, nowMillis = nowMillis)

    private fun ensureAndPulse(id: String, type: NodeType, label: String, nowMillis: Long): GraphNode {
        val existing = repo.getNode(id)
        val base = existing ?: GraphNode(id = id, type = type, label = label, createdAtMillis = nowMillis)
        val pulsed = ActivationPulseGenerator.pulse(base, nowMillis)
        val withImportance = pulsed.copy(importance = pulsed.importance + 0.1)
        repo.upsertNode(withImportance)
        return withImportance
    }
}
