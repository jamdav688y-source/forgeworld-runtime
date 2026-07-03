package substrate.core.pipeline

import substrate.core.model.Classification
import substrate.core.model.NodeType
import substrate.core.model.NormalizedEvent

/**
 * Stage 3: Classify. Runtime Invariant #3 — every event is classified before
 * execution. Deterministic keyword scoring: no network call, no hidden model,
 * fully inspectable via [Classification.matchedKeywords].
 */
object EventClassifier {
    private val KEYWORDS: Map<NodeType, Set<String>> = mapOf(
        NodeType.OBSERVATION to setOf("noticed", "observed", "saw", "watching", "signal", "spotted"),
        NodeType.MEMORY to setOf("remember", "recall", "memory", "remind", "recollect"),
        NodeType.RESEARCH to setOf("research", "paper", "study", "investigate", "hypothesis", "source", "finding"),
        NodeType.PROJECTS to setOf("project", "build", "ship", "milestone", "roadmap", "feature", "release"),
        NodeType.RUNTIME to setOf("runtime", "pipeline", "system", "deploy", "crash", "bug", "error", "latency", "outage"),
        NodeType.GOVERNANCE to setOf("governance", "policy", "constitution", "review", "audit", "compliance", "approve", "reject", "violation"),
        NodeType.COMMERCIAL to setOf("client", "revenue", "deal", "pricing", "contract", "sale", "opportunity", "invoice", "customer", "proposal"),
        NodeType.MEDIA to setOf("post", "video", "image", "publish", "linkedin", "article", "photo", "caption"),
        NodeType.LEARNING to setOf("learn", "course", "tutorial", "practice", "skill", "lesson"),
        NodeType.SYNCHRONIZATION to setOf("sync", "backup", "merge", "commit", "push", "pull", "export", "archive"),
    )

    /** Below this confidence, [substrate.core.pipeline.GovernanceValidator] flags the event for review. */
    const val MIN_CONFIDENCE_FOR_AUTO_EXECUTION = 0.34

    fun classify(normalized: NormalizedEvent): Classification {
        val words = normalized.cleanedText.lowercase()
            .split(Regex("[^a-z0-9]+"))
            .filter { it.isNotBlank() }
            .toSet()
        val tagWords = normalized.extractedTags
            .map { it.lowercase().trimStart('#', '@').substringAfter("project:") }
            .toSet()
        val haystack = words + tagWords

        val scores = KEYWORDS.mapValues { (_, kws) -> kws.count { it in haystack } }
        val totalMatches = scores.values.sum()
        val best = scores.entries.filter { it.value > 0 }.maxByOrNull { it.value }

        if (best == null) {
            return Classification(
                primaryType = NodeType.OBSERVATION,
                confidence = 0.15,
                matchedKeywords = emptyList(),
                secondaryTypes = emptyList(),
            )
        }

        val matched = KEYWORDS.getValue(best.key).filter { it in haystack }
        val confidence = (best.value.toDouble() / totalMatches).coerceIn(0.0, 1.0)
        val secondary = scores.filterKeys { it != best.key }.filterValues { it > 0 }.keys.toList()

        return Classification(
            primaryType = best.key,
            confidence = confidence,
            matchedKeywords = matched,
            secondaryTypes = secondary,
        )
    }
}
