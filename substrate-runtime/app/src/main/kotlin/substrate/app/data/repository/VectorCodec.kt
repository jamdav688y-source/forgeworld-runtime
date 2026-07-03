package substrate.app.data.repository

/**
 * Deliberately minimal manual codec for a `Map<String, Double>` term-frequency
 * vector, so `app` doesn't need a JSON/serialization dependency just to persist
 * it. Keys must not contain '=' or ';' (tokens from [substrate.core.pipeline.VectorIndex]
 * never do — they're `[a-z0-9]+` only).
 */
fun encodeVector(vector: Map<String, Double>): String =
    vector.entries.joinToString(";") { (k, v) -> "$k=$v" }

fun decodeVector(encoded: String): Map<String, Double> {
    if (encoded.isBlank()) return emptyMap()
    return encoded.split(";").filter { it.isNotBlank() }.associate {
        val (k, v) = it.split("=", limit = 2)
        k to v.toDouble()
    }
}
