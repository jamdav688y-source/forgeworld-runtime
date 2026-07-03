package substrate.core.model

/**
 * Output of the Classify stage (Runtime Invariant #3: every event is classified
 * before execution). `confidence` is in [0,1] and `matchedKeywords` makes the
 * decision inspectable rather than opaque.
 */
data class Classification(
    val primaryType: NodeType,
    val confidence: Double,
    val matchedKeywords: List<String>,
    val secondaryTypes: List<NodeType> = emptyList(),
)
