package substrate.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import substrate.core.model.Event
import substrate.core.model.NodeType
import substrate.core.pipeline.EventClassifier
import substrate.core.pipeline.EventNormalizer

class EventClassifierTest {

    private fun normalize(text: String) = EventNormalizer.normalize(
        Event(id = "e1", actor = "dave", text = text, occurredAtMillis = 0L),
    )

    @Test
    fun `classifies a governance-worded event as GOVERNANCE`() {
        val classification = EventClassifier.classify(normalize("Requesting review and approval under the constitution before this can persist"))
        assertEquals(NodeType.GOVERNANCE, classification.primaryType)
        assertTrue(classification.matchedKeywords.isNotEmpty())
    }

    @Test
    fun `classifies a commercial-worded event as COMMERCIAL`() {
        val classification = EventClassifier.classify(normalize("Client signed the contract, revenue opportunity confirmed"))
        assertEquals(NodeType.COMMERCIAL, classification.primaryType)
    }

    @Test
    fun `falls back to OBSERVATION with low confidence when nothing matches`() {
        val classification = EventClassifier.classify(normalize("xyz qwerty zzz"))
        assertEquals(NodeType.OBSERVATION, classification.primaryType)
        assertTrue(classification.confidence < EventClassifier.MIN_CONFIDENCE_FOR_AUTO_EXECUTION)
    }
}
