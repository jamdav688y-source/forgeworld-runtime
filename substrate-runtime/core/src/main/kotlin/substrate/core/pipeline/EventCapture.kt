package substrate.core.pipeline

import java.util.UUID
import substrate.core.model.Event

/**
 * Stage 1: Capture. Runtime Invariants #1/#2 — every interaction becomes an
 * Event, and every Event gets a unique id assigned exactly once, here.
 */
object EventCapture {
    fun capture(
        actor: String,
        text: String,
        occurredAtMillis: Long,
        explicitTags: List<String> = emptyList(),
        dependsOnEventIds: List<String> = emptyList(),
    ): Event = Event(
        id = UUID.randomUUID().toString(),
        actor = actor,
        text = text,
        occurredAtMillis = occurredAtMillis,
        explicitTags = explicitTags,
        dependsOnEventIds = dependsOnEventIds,
    )
}
