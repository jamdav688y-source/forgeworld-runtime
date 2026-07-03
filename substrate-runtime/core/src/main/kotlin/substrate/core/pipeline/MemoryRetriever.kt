package substrate.core.pipeline

import substrate.core.model.MemoryRecord

/** Stage 5: Retrieve Related Memory — local cosine-similarity search, no network. */
object MemoryRetriever {
    const val SIMILARITY_THRESHOLD = 0.15
    const val MAX_RESULTS = 5

    fun retrieveRelated(vector: Map<String, Double>, memories: List<MemoryRecord>): List<Pair<MemoryRecord, Double>> =
        memories
            .map { it to VectorIndex.cosineSimilarity(vector, it.vector) }
            .filter { it.second >= SIMILARITY_THRESHOLD }
            .sortedByDescending { it.second }
            .take(MAX_RESULTS)
}
