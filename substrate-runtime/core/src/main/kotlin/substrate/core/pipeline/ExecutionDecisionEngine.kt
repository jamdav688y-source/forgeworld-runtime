package substrate.core.pipeline

import substrate.core.model.CommercialAssessment
import substrate.core.model.ExecutionDecisionKind
import substrate.core.model.ExecutionOutcome
import substrate.core.model.GovernanceDecision

/**
 * Stage 9: Execution Decision. REJECT wins over HOLD wins over EXECUTE — a
 * blocking governance violation always rejects regardless of commercial
 * score; a non-blocking violation (e.g. low classification confidence) holds
 * the event for review instead of silently auto-executing it.
 */
object ExecutionDecisionEngine {
    fun decide(governance: GovernanceDecision, commercial: CommercialAssessment): ExecutionOutcome {
        if (!governance.allowed) {
            return ExecutionOutcome(
                kind = ExecutionDecisionKind.REJECT,
                reasons = governance.violations.filter { it.blocking }.map { "${it.rule}: ${it.detail}" },
            )
        }

        val softViolations = governance.violations.filterNot { it.blocking }
        if (softViolations.isNotEmpty()) {
            return ExecutionOutcome(
                kind = ExecutionDecisionKind.HOLD,
                reasons = softViolations.map { "${it.rule}: ${it.detail}" },
            )
        }

        val reasons = mutableListOf("Governance validation passed with no violations.")
        if (commercial.score > 0.0) {
            reasons += "Commercial opportunity score ${"%.2f".format(commercial.score)}: ${commercial.rationale}"
        }
        return ExecutionOutcome(kind = ExecutionDecisionKind.EXECUTE, reasons = reasons)
    }
}
