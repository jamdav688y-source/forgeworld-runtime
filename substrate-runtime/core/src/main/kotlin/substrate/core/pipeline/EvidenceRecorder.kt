package substrate.core.pipeline

import java.util.UUID
import substrate.core.model.EvidenceRecord
import substrate.core.model.NormalizedEvent
import substrate.core.repository.EvidenceRepository

/**
 * Stage 10: Evidence Recording. Runtime Invariant #4 — every event creates
 * evidence. Reuses an existing record if one is already present for this
 * event id (Resource Conservation Mandate: no duplicate records) instead of
 * appending a second one, unlike the original bash `log_event.sh`, which had
 * no dedup concept at all.
 */
object EvidenceRecorder {
    fun record(
        normalized: NormalizedEvent,
        repo: EvidenceRepository,
        nowMillis: Long,
    ): EvidenceRecord {
        repo.getEvidenceForEvent(normalized.source.id)?.let { return it }
        val evidence = EvidenceRecord(
            id = UUID.randomUUID().toString(),
            eventId = normalized.source.id,
            description = "actor=${normalized.source.actor}; text=\"${normalized.cleanedText}\"; tags=${normalized.extractedTags}",
            createdAtMillis = nowMillis,
        )
        repo.upsertEvidence(evidence)
        return evidence
    }
}
