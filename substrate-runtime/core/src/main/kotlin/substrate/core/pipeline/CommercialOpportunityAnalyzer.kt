package substrate.core.pipeline

import substrate.core.model.Classification
import substrate.core.model.CommercialAssessment
import substrate.core.model.NodeType
import substrate.core.model.NormalizedEvent

/**
 * Stage 8: Commercial Opportunity Analysis. Heuristic, inspectable scoring —
 * not a black box. This is the first working implementation of the
 * "Opportunity" resource the original doctrine (world_state.json, rpg/player.json)
 * only ever declared as an unused numeric field.
 */
object CommercialOpportunityAnalyzer {
    private val OPPORTUNITY_KEYWORDS = setOf(
        "client", "revenue", "deal", "pricing", "contract", "sale", "opportunity",
        "invoice", "customer", "proposal", "partnership", "funding",
    )

    fun assess(normalized: NormalizedEvent, classification: Classification): CommercialAssessment {
        val signals = mutableListOf<String>()
        var score = 0.0

        if (classification.primaryType == NodeType.COMMERCIAL) {
            score += 0.5
            signals += "primary classification is COMMERCIAL"
        }
        if (NodeType.COMMERCIAL in classification.secondaryTypes) {
            score += 0.2
            signals += "COMMERCIAL present as a secondary classification"
        }

        val lower = normalized.cleanedText.lowercase()
        val hits = OPPORTUNITY_KEYWORDS.filter { it in lower }
        if (hits.isNotEmpty()) {
            score += (0.1 * hits.size).coerceAtMost(0.4)
            signals += "keyword matches: ${hits.joinToString(", ")}"
        }

        if (normalized.extractedTags.any { it.equals("@opportunity", ignoreCase = true) }) {
            score += 0.2
            signals += "explicit @opportunity tag"
        }

        val finalScore = score.coerceIn(0.0, 1.0)
        val rationale = if (signals.isEmpty()) {
            "No commercial signals detected."
        } else {
            "Score derived from: ${signals.joinToString("; ")}."
        }
        return CommercialAssessment(score = finalScore, signals = signals, rationale = rationale)
    }
}
