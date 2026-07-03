package substrate.core.pipeline

import java.util.UUID
import substrate.core.model.Classification
import substrate.core.model.EdgeType
import substrate.core.model.EvidenceRecord
import substrate.core.model.MemoryRecord
import substrate.core.model.NodeType
import substrate.core.model.NormalizedEvent
import substrate.core.repository.GraphRepository
import substrate.core.repository.MemoryRepository

data class ReinforcementResult(
    val memory: MemoryRecord,
    val touchedEdgeIds: List<String>,
)

/**
 * Stage 11: Relationship Reinforcement. Runs after evidence exists, so this is
 * the only place the EVIDENCE edge type (and the searchable [MemoryRecord]
 * required by Runtime Invariant #6) get created — "evidence precedes memory"
 * is a structural guarantee here, not just a documented rule.
 */
object RelationshipReinforcer {
    fun reinforce(
        topicNodeId: String,
        normalized: NormalizedEvent,
        classification: Classification,
        evidence: EvidenceRecord,
        graphRepo: GraphRepository,
        memoryRepo: MemoryRepository,
        nowMillis: Long,
    ): ReinforcementResult {
        val edges = mutableListOf<String>()

        val memoryAnchor = graphRepo.getNode("domain:${NodeType.MEMORY}")
            ?: substrate.core.model.GraphNode(
                id = "domain:${NodeType.MEMORY}",
                type = NodeType.MEMORY,
                label = NodeType.MEMORY.name,
                createdAtMillis = nowMillis,
            )
        val pulsedAnchor = ActivationPulseGenerator.pulse(memoryAnchor, nowMillis)
            .let { it.copy(importance = it.importance + 0.1) }
        graphRepo.upsertNode(pulsedAnchor)

        edges += GraphEdgeOps.reinforce(graphRepo, topicNodeId, pulsedAnchor.id, EdgeType.EVIDENCE, 1.0, nowMillis).id

        // Strengthen the topic node itself now that evidence + memory have landed —
        // a fully reinforced activation, one importance step above the initial pulse.
        graphRepo.getNode(topicNodeId)?.let { node ->
            graphRepo.upsertNode(node.copy(importance = node.importance + 0.1))
        }

        val vector = VectorIndex.vectorize(normalized.cleanedText)
        val existing = memoryRepo.getAllMemories().firstOrNull { it.eventId == normalized.source.id }
        val memory = existing ?: MemoryRecord(
            id = UUID.randomUUID().toString(),
            eventId = normalized.source.id,
            evidenceId = evidence.id,
            nodeId = topicNodeId,
            summary = normalized.cleanedText,
            vector = vector,
            createdAtMillis = nowMillis,
        )
        memoryRepo.upsertMemory(memory)

        return ReinforcementResult(memory = memory, touchedEdgeIds = edges)
    }
}
