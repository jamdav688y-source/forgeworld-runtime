package substrate.core

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import substrate.core.model.Event
import substrate.core.pipeline.EventClassifier
import substrate.core.pipeline.EventNormalizer
import substrate.core.pipeline.GovernanceValidator

class GovernanceValidatorTest {

    @Test
    fun `blank actor is a blocking violation`() {
        val normalized = EventNormalizer.normalize(Event(id = "e1", actor = "", text = "shipped the milestone", occurredAtMillis = 0L))
        val classification = EventClassifier.classify(normalized)
        val decision = GovernanceValidator.validate(normalized, classification, evidenceAlreadyExists = false)
        assertFalse(decision.allowed)
        assertTrue(decision.violations.any { it.rule == "ACCOUNTABLE_ACTOR" && it.blocking })
    }

    @Test
    fun `self-dependency is a blocking violation`() {
        val normalized = EventNormalizer.normalize(
            Event(id = "e1", actor = "dave", text = "loops on itself", occurredAtMillis = 0L, dependsOnEventIds = listOf("e1")),
        )
        val classification = EventClassifier.classify(normalized)
        val decision = GovernanceValidator.validate(normalized, classification, evidenceAlreadyExists = false)
        assertFalse(decision.allowed)
        assertTrue(decision.violations.any { it.rule == "NO_SELF_DEPENDENCY" })
    }

    @Test
    fun `well-formed high-confidence event is allowed with no violations`() {
        val normalized = EventNormalizer.normalize(
            Event(id = "e1", actor = "dave", text = "client signed the contract, revenue opportunity confirmed", occurredAtMillis = 0L),
        )
        val classification = EventClassifier.classify(normalized)
        val decision = GovernanceValidator.validate(normalized, classification, evidenceAlreadyExists = false)
        assertTrue(decision.allowed)
        assertTrue(decision.violations.isEmpty())
    }

    @Test
    fun `low-confidence classification is a non-blocking violation that still allows the event`() {
        val normalized = EventNormalizer.normalize(Event(id = "e1", actor = "dave", text = "zzz qqq", occurredAtMillis = 0L))
        val classification = EventClassifier.classify(normalized)
        val decision = GovernanceValidator.validate(normalized, classification, evidenceAlreadyExists = false)
        assertTrue(decision.allowed, "non-blocking violations must not flip allowed to false")
        assertTrue(decision.violations.any { it.rule == "CLASSIFICATION_CONFIDENCE_BELOW_THRESHOLD" && !it.blocking })
    }
}
