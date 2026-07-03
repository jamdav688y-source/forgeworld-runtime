package substrate.core.pipeline

import kotlin.math.sqrt

/**
 * Minimal local vector representation: a normalized bag-of-words term-frequency
 * vector plus cosine similarity. Deliberately not full TF-IDF (no corpus-wide
 * document-frequency statistics are maintained) — this keeps memory retrieval
 * deterministic, dependency-free, and fully offline, at the cost of not
 * down-weighting common words. Documented here rather than overclaimed.
 */
object VectorIndex {
    private val TOKEN = Regex("[^a-z0-9]+")

    // A small, fixed stopword list — not corpus-derived IDF, but enough to stop
    // high-frequency connective words from dominating cosine similarity between
    // otherwise unrelated texts.
    private val STOPWORDS = setOf(
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "has", "had",
        "was", "were", "with", "this", "that", "from", "have", "been", "will",
        "just", "into", "your", "our", "its", "his", "her", "who", "how", "why",
    )

    fun vectorize(text: String): Map<String, Double> {
        val tokens = text.lowercase().split(TOKEN).filter { it.length > 2 && it !in STOPWORDS }
        if (tokens.isEmpty()) return emptyMap()
        val counts = tokens.groupingBy { it }.eachCount()
        val max = counts.values.max().toDouble()
        return counts.mapValues { it.value / max }
    }

    fun cosineSimilarity(a: Map<String, Double>, b: Map<String, Double>): Double {
        if (a.isEmpty() || b.isEmpty()) return 0.0
        val sharedKeys = a.keys.intersect(b.keys)
        if (sharedKeys.isEmpty()) return 0.0
        val dot = sharedKeys.sumOf { a.getValue(it) * b.getValue(it) }
        val normA = sqrt(a.values.sumOf { it * it })
        val normB = sqrt(b.values.sumOf { it * it })
        if (normA == 0.0 || normB == 0.0) return 0.0
        return dot / (normA * normB)
    }
}
