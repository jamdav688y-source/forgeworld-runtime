package substrate.core.pipeline

import substrate.core.model.Event
import substrate.core.model.NormalizedEvent

/** Stage 2: Normalize. Collapses whitespace and extracts `#tag`/`@mention`/`project:x` markers. */
object EventNormalizer {
    private val WHITESPACE = Regex("\\s+")

    // "#project:x" is matched before the plain "#tag" alternative so the whole
    // "project:x" survives instead of the match stopping at the colon.
    private val TAG_PATTERN = Regex(
        "(?:^|\\s)(#project:[A-Za-z0-9_-]+|project:[A-Za-z0-9_-]+|#[A-Za-z0-9_-]+|@[A-Za-z0-9_-]+)",
    )

    fun normalize(event: Event): NormalizedEvent {
        val cleaned = event.text.trim().replace(WHITESPACE, " ")
        val extracted = TAG_PATTERN.findAll(cleaned)
            .map { it.groupValues[1] }
            .map { if (it.startsWith("#project:")) it.removePrefix("#") else it }
            .toList()
        return NormalizedEvent(
            source = event,
            cleanedText = cleaned,
            extractedTags = (extracted + event.explicitTags).distinct(),
        )
    }
}
