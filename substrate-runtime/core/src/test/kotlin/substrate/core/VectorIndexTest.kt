package substrate.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import substrate.core.pipeline.VectorIndex

class VectorIndexTest {

    @Test
    fun `identical text has cosine similarity of 1`() {
        val a = VectorIndex.vectorize("the crystal warden guards the northern ruins")
        val b = VectorIndex.vectorize("the crystal warden guards the northern ruins")
        assertEquals(1.0, VectorIndex.cosineSimilarity(a, b), 1e-9)
    }

    @Test
    fun `unrelated text has low similarity`() {
        val a = VectorIndex.vectorize("player defeated the crystal warden in the ruins")
        val b = VectorIndex.vectorize("invoice sent to the client for the quarterly contract")
        assertTrue(VectorIndex.cosineSimilarity(a, b) < 0.2)
    }

    @Test
    fun `empty text has zero similarity to anything`() {
        val a = VectorIndex.vectorize("")
        val b = VectorIndex.vectorize("some real content here")
        assertEquals(0.0, VectorIndex.cosineSimilarity(a, b))
    }
}
