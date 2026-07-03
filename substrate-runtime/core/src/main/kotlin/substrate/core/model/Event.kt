package substrate.core.model

/**
 * Raw input to the substrate. Every user interaction becomes exactly one of these.
 * `id` is assigned at capture time (Runtime Invariant #2: every event receives a
 * unique identifier) and is never reassigned downstream.
 */
data class Event(
    val id: String,
    val actor: String,
    val text: String,
    val occurredAtMillis: Long,
    val explicitTags: List<String> = emptyList(),
    val dependsOnEventIds: List<String> = emptyList(),
)

/** Event after whitespace/casing cleanup and tag extraction (stage: Normalize). */
data class NormalizedEvent(
    val source: Event,
    val cleanedText: String,
    val extractedTags: List<String>,
)
