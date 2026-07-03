package substrate.core.model

enum class ExecutionDecisionKind { EXECUTE, HOLD, REJECT }

/** Final Execution Decision stage output — always traceable to the decisions that produced it. */
data class ExecutionOutcome(
    val kind: ExecutionDecisionKind,
    val reasons: List<String>,
)
