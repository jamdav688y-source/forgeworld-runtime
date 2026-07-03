package substrate.core.pipeline

import substrate.core.model.Classification
import substrate.core.model.GovernanceDecision
import substrate.core.model.GovernanceViolation
import substrate.core.model.NormalizedEvent

/**
 * Stage 7: Governance Validation. Encodes the eight Runtime Invariants plus
 * the FORGEWORLD Constitution v3 Core Laws (governance/CONSTITUTION_v3.txt in
 * the repo root doctrine) as executable checks. Unlike `resolve_event.sh` in
 * the original bash scaffold — which accepted every event unconditionally —
 * this is the first point in FORGEWORLD's history where governance can
 * actually reject or hold something.
 */
object GovernanceValidator {

    fun validate(
        normalized: NormalizedEvent,
        classification: Classification,
        evidenceAlreadyExists: Boolean,
    ): GovernanceDecision {
        val violations = mutableListOf<GovernanceViolation>()

        // Constitution: "Authority emerges from traceable evidence" — no anonymous actor.
        if (normalized.source.actor.isBlank()) {
            violations += GovernanceViolation(
                rule = "ACCOUNTABLE_ACTOR",
                detail = "Event has no actor; authority requires accountability.",
                blocking = true,
            )
        }

        // Resource Conservation Mandate: "No storage without reconstruction value."
        if (normalized.cleanedText.isBlank()) {
            violations += GovernanceViolation(
                rule = "NON_EMPTY_CONTENT",
                detail = "Event has no reconstructable content.",
                blocking = true,
            )
        }

        // Continuity preserves explainability — an event cannot depend on itself.
        if (normalized.source.id in normalized.source.dependsOnEventIds) {
            violations += GovernanceViolation(
                rule = "NO_SELF_DEPENDENCY",
                detail = "Event lists itself as a dependency, which would make the causal chain unexplainable.",
                blocking = true,
            )
        }

        // Runtime Invariant #3, enforced (not just checked-for-presence): a low-confidence
        // classification is not a safe basis for autonomous execution — hold for review.
        if (classification.confidence < EventClassifier.MIN_CONFIDENCE_FOR_AUTO_EXECUTION) {
            violations += GovernanceViolation(
                rule = "CLASSIFICATION_CONFIDENCE_BELOW_THRESHOLD",
                detail = "Classification confidence ${"%.2f".format(classification.confidence)} is below the " +
                    "${EventClassifier.MIN_CONFIDENCE_FOR_AUTO_EXECUTION} threshold for autonomous execution.",
                blocking = false,
            )
        }

        // Resource Conservation Mandate: "No duplicate records." If evidence for this
        // event id already exists, EvidenceRecorder must reuse it rather than create a
        // second record — flagged non-blocking so the event still proceeds, but the
        // dedup requirement is visible in the audit trail.
        if (evidenceAlreadyExists) {
            violations += GovernanceViolation(
                rule = "REUSE_EXISTING_EVIDENCE",
                detail = "Evidence already exists for this event id; EvidenceRecorder must not duplicate it.",
                blocking = false,
            )
        }

        val blocking = violations.any { it.blocking }
        return GovernanceDecision(
            allowed = !blocking,
            violations = violations,
            notes = listOf("Can the present state explain how it became itself?"),
        )
    }
}
