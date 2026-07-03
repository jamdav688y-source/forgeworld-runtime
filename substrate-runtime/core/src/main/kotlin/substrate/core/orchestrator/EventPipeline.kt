package substrate.core.orchestrator

import java.util.UUID
import substrate.core.model.AuditTrailEntry
import substrate.core.model.PipelineResult
import substrate.core.model.SyncQueueItem
import substrate.core.pipeline.CommercialOpportunityAnalyzer
import substrate.core.pipeline.EventCapture
import substrate.core.pipeline.EventClassifier
import substrate.core.pipeline.EventNormalizer
import substrate.core.pipeline.EvidenceRecorder
import substrate.core.pipeline.ExecutionDecisionEngine
import substrate.core.pipeline.GovernanceValidator
import substrate.core.pipeline.MemoryRetriever
import substrate.core.pipeline.PipelineStage
import substrate.core.pipeline.RelationshipGraphEngine
import substrate.core.pipeline.RelationshipReinforcer
import substrate.core.pipeline.RuntimeSnapshotBuilder
import substrate.core.pipeline.VectorIndex
import substrate.core.repository.AuditTrailRepository
import substrate.core.repository.EvidenceRepository
import substrate.core.repository.GraphRepository
import substrate.core.repository.MemoryRepository
import substrate.core.repository.SyncQueueRepository

/**
 * The single entry point implementing the full MICRO_SUBSTRATE_RUNTIME_V1 event
 * pipeline:
 *
 * Capture -> Normalize -> Classify -> Activation Pulse -> Retrieve Related Memory
 * -> Relationship Expansion -> Governance Validation -> Commercial Opportunity
 * Analysis -> Execution Decision -> Evidence Recording -> Relationship
 * Reinforcement -> Render Updated Neural Landscape.
 *
 * Every stage appends exactly one [AuditTrailEntry] — the Observability
 * requirement ("no hidden reasoning without an observable audit trail") is
 * structural, not optional. All twelve stages run for every event
 * unconditionally: a REJECTed or HELD event still receives evidence and
 * becomes searchable memory (Runtime Invariants #4/#6 are unconditional in
 * the spec); the execution decision only gates whether external action
 * beyond substrate bookkeeping would be taken. No external action is wired
 * up yet (see ARCHITECTURE_INDEX.md), so today EXECUTE/HOLD/REJECT is purely
 * observable state.
 */
class EventPipeline(
    private val graphRepository: GraphRepository,
    private val memoryRepository: MemoryRepository,
    private val evidenceRepository: EvidenceRepository,
    private val auditTrailRepository: AuditTrailRepository,
    private val syncQueueRepository: SyncQueueRepository,
    private val nowMillisProvider: () -> Long = { System.currentTimeMillis() },
) {
    private val relationshipGraphEngine = RelationshipGraphEngine(graphRepository)

    fun submit(actor: String, text: String, explicitTags: List<String> = emptyList(), dependsOnEventIds: List<String> = emptyList()): PipelineResult {
        val now = nowMillisProvider()

        val event = EventCapture.capture(actor, text, now, explicitTags, dependsOnEventIds)

        fun log(stage: String, summary: String) {
            val entry = AuditTrailEntry(
                id = UUID.randomUUID().toString(),
                eventId = event.id,
                stage = stage,
                summary = summary,
                timestampMillis = nowMillisProvider(),
            )
            auditTrailRepository.append(entry)
        }

        log(PipelineStage.CAPTURE, "id=${event.id} actor=$actor")

        val normalized = EventNormalizer.normalize(event)
        log(PipelineStage.NORMALIZE, "cleanedText=\"${normalized.cleanedText}\" tags=${normalized.extractedTags}")

        val classification = EventClassifier.classify(normalized)
        log(PipelineStage.CLASSIFY, "primary=${classification.primaryType} confidence=${"%.2f".format(classification.confidence)} matched=${classification.matchedKeywords}")

        // Activation pulse for the eventual topic node happens inside RelationshipGraphEngine
        // (it needs the topic id, which is only known once expansion computes it), but we
        // still log this as its own observable stage per the spec's pipeline diagram.
        log(PipelineStage.ACTIVATION_PULSE, "activation pulse scheduled for topic node")

        val vector = VectorIndex.vectorize(normalized.cleanedText)
        val related = MemoryRetriever.retrieveRelated(vector, memoryRepository.getAllMemories())
        log(PipelineStage.MEMORY_RETRIEVAL, "retrieved=${related.size} memories above similarity threshold ${MemoryRetriever.SIMILARITY_THRESHOLD}")

        val expansion = relationshipGraphEngine.expand(normalized, classification, related, now)
        log(PipelineStage.RELATIONSHIP_EXPANSION, "topicNode=${expansion.topicNodeId} activatedNodes=${expansion.activatedNodeIds.size} edges=${expansion.touchedEdgeIds.size}")

        val evidenceAlreadyExists = evidenceRepository.getEvidenceForEvent(event.id) != null
        val governance = GovernanceValidator.validate(normalized, classification, evidenceAlreadyExists)
        log(PipelineStage.GOVERNANCE_VALIDATION, "allowed=${governance.allowed} violations=${governance.violations.map { it.rule }}")

        val commercial = CommercialOpportunityAnalyzer.assess(normalized, classification)
        log(PipelineStage.COMMERCIAL_ANALYSIS, "score=${"%.2f".format(commercial.score)} signals=${commercial.signals}")

        val executionOutcome = ExecutionDecisionEngine.decide(governance, commercial)
        log(PipelineStage.EXECUTION_DECISION, "kind=${executionOutcome.kind} reasons=${executionOutcome.reasons}")

        val evidence = EvidenceRecorder.record(normalized, evidenceRepository, now)
        log(PipelineStage.EVIDENCE_RECORDING, "evidenceId=${evidence.id}")

        val reinforcement = RelationshipReinforcer.reinforce(
            topicNodeId = expansion.topicNodeId,
            normalized = normalized,
            classification = classification,
            evidence = evidence,
            graphRepo = graphRepository,
            memoryRepo = memoryRepository,
            nowMillis = now,
        )
        log(PipelineStage.RELATIONSHIP_REINFORCEMENT, "memoryId=${reinforcement.memory.id} edges=${reinforcement.touchedEdgeIds.size}")

        RuntimeSnapshotBuilder.build(graphRepository, now)
        log(PipelineStage.RUNTIME_SNAPSHOT, "snapshot generated from live repository state (no synthetic values)")

        syncQueueRepository.enqueue(
            SyncQueueItem(
                id = UUID.randomUUID().toString(),
                eventId = event.id,
                payload = "event=${event.id} outcome=${executionOutcome.kind}",
                enqueuedAtMillis = now,
            ),
        )

        return PipelineResult(
            event = event,
            normalized = normalized,
            classification = classification,
            activatedNodeIds = expansion.activatedNodeIds,
            retrievedMemoryIds = related.map { it.first.id },
            newOrUpdatedEdgeIds = (expansion.touchedEdgeIds + reinforcement.touchedEdgeIds).distinct(),
            governanceDecision = governance,
            commercialAssessment = commercial,
            executionOutcome = executionOutcome,
            evidence = evidence,
            memory = reinforcement.memory,
            auditTrail = auditTrailRepository.getTrailForEvent(event.id),
        )
    }
}
