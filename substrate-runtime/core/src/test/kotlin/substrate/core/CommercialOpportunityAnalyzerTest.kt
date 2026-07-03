package substrate.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import substrate.core.model.Event
import substrate.core.pipeline.CommercialOpportunityAnalyzer
import substrate.core.pipeline.EventClassifier
import substrate.core.pipeline.EventNormalizer

class CommercialOpportunityAnalyzerTest {

    @Test
    fun `commercial-worded event scores above zero with signals listed`() {
        val normalized = EventNormalizer.normalize(
            Event(id = "e1", actor = "dave", text = "client signed the contract, revenue opportunity confirmed", occurredAtMillis = 0L),
        )
        val classification = EventClassifier.classify(normalized)
        val assessment = CommercialOpportunityAnalyzer.assess(normalized, classification)
        assertTrue(assessment.score > 0.0)
        assertTrue(assessment.signals.isNotEmpty())
    }

    @Test
    fun `unrelated event scores zero with no signals`() {
        val normalized = EventNormalizer.normalize(
            Event(id = "e1", actor = "dave", text = "took a walk in the park", occurredAtMillis = 0L),
        )
        val classification = EventClassifier.classify(normalized)
        val assessment = CommercialOpportunityAnalyzer.assess(normalized, classification)
        assertEquals(0.0, assessment.score)
        assertTrue(assessment.signals.isEmpty())
    }
}
