package substrate.core.model

/**
 * A single failed check, named after the invariant or constitutional law it
 * enforces. `blocking = true` means the event must be REJECTed outright;
 * `blocking = false` means it may proceed to HOLD (queued for review) rather
 * than being discarded.
 */
data class GovernanceViolation(
    val rule: String,
    val detail: String,
    val blocking: Boolean = true,
)

/**
 * Result of the Governance Validation stage. `allowed = false` means the pipeline
 * must HOLD or REJECT — there is no path in [substrate.core.pipeline.EventPipeline]
 * that lets an event proceed to execution while violations are non-empty.
 */
data class GovernanceDecision(
    val allowed: Boolean,
    val violations: List<GovernanceViolation>,
    val notes: List<String>,
)
