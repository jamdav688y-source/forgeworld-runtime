# PROOF 001 Evidence Manifest

Every object produced by the two proof runs described in
`PROOF_001_EXECUTION_REPORT.md`, in pipeline order. Full JSON (every
field, every object) is in `proof_001_run_output.json` in this directory —
this manifest is the human-readable index into it, organized the way the
mission's own acceptance test asks for: **observation, inference,
validation, promotion** kept visibly distinct, never collapsed into one
undifferentiated list.

## OBSERVATION

Content-addressed, hash-verified captures. `source_image_sha256` is the
join key for everything downstream.

| id | sha256 (first 16) | dims | capture_source | confidence |
|---|---|---|---|---|
| OBS-4b64bc57057e | bec6aac880d86669 | 64×64 | termux_manual_upload_synthetic | 1.0 |
| OBS-eb16ba7226ed | 24c47a150a90b812 | 1080×2388 | termux_manual_upload_real | 1.0 |
| (obs_1555, from `screenshot_1555.png`) | 0b843804c78b6994 | 64×64 | proof_run | 1.0 |
| (obs_different, from `screenshot_different.png`) | 304c5014fb567574 | 64×64 | proof_run | 1.0 |

`confidence=1.0` for every VisualObservation: possessing the bytes and
their sha256 is a measured fact, not a probabilistic inference (see
`schema.new_visual_observation`'s own comment).

### Signals (ExtractedSignal)

| id | signal_type | value | provider | confidence |
|---|---|---|---|---|
| SIG-0c2837ec4859 | ocr_text | "Pocket Cortex\nWhatsApp Intelligence Membrane" | mock:fixture_ocr | 0.92 |
| SIG-4469fcb10911 | visual_fingerprint | 0000552a552a552a | *(none — deterministic computation)* | 1.0 |
| SIG-7c1c544281bb | entity (platform_name) | WhatsApp | *(none — keyword match)* | 1.0 |
| SIG-aa79491d5500 | entity (platform_name) | Pocket Cortex | *(none)* | 1.0 |
| SIG-cf5d1623edf4 | entity (page_title) | "WhatsApp Intelligence Membrane" | *(none — heuristic)* | 0.6 |
| SIG-595a02c16396 | ocr_text | "Pocket Cortex\nGitHub — forgeworld-runtime" | mock:fixture_ocr | 0.87 |
| SIG-b6607280fcf0 | visual_fingerprint | 000b0f0f17030100 | *(none)* | 1.0 |
| SIG-3940bb8901e5 | entity (platform_name) | GitHub | *(none)* | 1.0 |
| SIG-750b4e3b5485 | entity (platform_name) | Pocket Cortex | *(none)* | 1.0 |
| SIG-b2905c9422f3 | entity (platform_name) | ForgeWorld | *(none)* | 1.0 |
| SIG-ba1964f3c57c | entity (page_title) | "GitHub — forgeworld-runtime" | *(none)* | 0.6 |

Entity confidence of `1.0` = exact word-boundary match against the known
platform list, never a fuzzy guess; page_title confidence `0.6` because
"the longest line is the title" is a documented heuristic, not a verified
fact (see `entities.py`'s module docstring).

## INFERENCE

Retrieved candidates — a provider's opinion, never validated at this
point. Every single one starts (and, in these runs, several remain)
`CANDIDATE_MATCH`.

| id | url | validation_status | retrieved for entity signal |
|---|---|---|---|
| CND-a1e8320b1f26 | en.wikipedia.org/wiki/WhatsApp | CANDIDATE_MATCH | SIG-7c1c544281bb (WhatsApp) |
| CND-038d210071c8 | www.whatsapp.com/ | CANDIDATE_MATCH | SIG-7c1c544281bb (WhatsApp) |
| CND-aae121623d67 | forgeworld.example/pocket-cortex | CANDIDATE_MATCH | SIG-aa79491d5500 (Pocket Cortex) |
| CND-c3a9e8f14dd5 | github.com/about | CANDIDATE_MATCH | SIG-3940bb8901e5 (GitHub) |
| CND-8e955bfab2d2 | status.example.com/github-outage | CANDIDATE_MATCH | SIG-3940bb8901e5 (GitHub) |
| CND-c45eb8d90828 | forgeworld.example/pocket-cortex | CANDIDATE_MATCH | SIG-750b4e3b5485 (Pocket Cortex) |

## VALIDATION

### EvidenceRelationship — independence-checked

| id | relationship_type | independence_basis |
|---|---|---|
| REL-fe0776e69895 | corroborates | 2 distinct, independent source domains: en.wikipedia.org, www.whatsapp.com |
| REL-9e5348dcabee | unrelated | only 1 distinct domain among 1 candidate — not independent |
| REL-19eea8bdd520 | contradicts | 1 source asserts, 1 disputes, across 2 distinct domains: github.com, status.example.com |
| REL-3fdb8c2f2997 | unrelated | only 1 distinct domain among 1 candidate — not independent |
| REL-7cfb0a03977a | near_duplicate | distinct sha256 (bec6aac880d8... vs 0b843804c78b...) — NOT identical; fingerprint hamming distance=0 ≤ threshold=8 |
| *(1554 vs different)* | *(none produced)* | hamming distance=42 > threshold=8 — correctly not forced into a relationship |

### ContradictionRecord — visible, unresolved

| id | validation_status | contradiction_state | description |
|---|---|---|---|
| CTR-9c091804c99c | unresolved | active | Candidates for query signal SIG-3940bb8901e5 disagree: github.com/about asserts vs. status.example.com/github-outage disputes |

`human_review_status=pending` on this record (set by
`schema.new_contradiction_record`) — a human has not yet acted on it, and
nothing in this codebase can silently resolve it.

### ExtractedClaim — evidence-classified

| id | validation_status (= evidence classification) | claim_text |
|---|---|---|
| CLM-9c1d7a182ab0 | corroborated-claim | WhatsApp is corroborated by independent sources (...) |
| CLM-88427a0e6dc8 | unverified-claim | Pocket Cortex has only single-source or non-independent support (...) |
| CLM-bcf3d342cc58 | contradicted-claim | GitHub is disputed across independent sources (...) |
| CLM-1f046b8dd70b | unverified-claim | Pocket Cortex has only single-source or non-independent support (...) |

## PROMOTION

### CapabilityProposal — always PROPOSED, never self-validated

| id | validation_status | grounded in claim |
|---|---|---|
| PRP-909c8b39b6da | PROPOSED | CLM-9c1d7a182ab0 (corroborated-claim) |
| PRP-8075e070287a | PROPOSED | CLM-88427a0e6dc8 (unverified-claim) |
| PRP-bbe661178aee | PROPOSED | CLM-bcf3d342cc58 (contradicted-claim) |
| PRP-cd157c8a1d8e | PROPOSED | CLM-1f046b8dd70b (unverified-claim) |

### PromotionDecision — the only human-authored object in this system

| id | decision | evidence_state | authority_decision | decided_by |
|---|---|---|---|---|
| PRO-7eb8c37c92ed | **PROMOTED** | SUPPORTED | HUMAN_ONLY | human:jamdav688y@gmail.com |
| PRO-b3f6dbf8ad58 | DEFERRED | OBSERVED (< required SUPPORTED) | HUMAN_ONLY | human:jamdav688y@gmail.com |
| PRO-cbafab135709 | DEFERRED | NOT_CHECKED (blocked by unresolved contradiction) | NOT_CHECKED | human:jamdav688y@gmail.com |
| PRO-2ca6b8da4f4e | DEFERRED | OBSERVED (< required SUPPORTED) | HUMAN_ONLY | human:jamdav688y@gmail.com |

Every row: `provider=null`, `human_review_status=reviewed` — structurally
enforced by `schema.validate_promotion_decision`, not merely by convention.

### Knowledge Vault — the only object that reached canonical memory

```
perception/ledgers/knowledge_vault.jsonl (gitignored, runtime-only):
  1 entry: proposal PRP-909c8b39b6da + promotion decision PRO-7eb8c37c92ed
  "Perception Gateway observation: WhatsApp is corroborated by
   independent sources (2 distinct, independent source domains:
   ['en.wikipedia.org', 'www.whatsapp.com'])"
```

Three other proposals were **not** promoted this run — one for
insufficient (single-source) evidence, one blocked outright by an
unresolved contradiction, one for insufficient evidence again. This 1-of-4
promotion rate across the two runs is not a bug: it is the gate working —
"A candidate cannot enter canonical memory without corroborating
evidence" held for 3 of 4 proposals.

## Execution Ledger coverage

61 `system=perception` records this run, across all 10 stage names the
pipeline defines:

```
CAPTURE: 5   HASH: 10   OCR: 4   FINGERPRINT: 8   CANDIDATE_RETRIEVAL: 13
SOURCE_CORROBORATION: 8   CLAIM_EXTRACTION: 4   CAPABILITY_PROPOSAL: 4
HUMAN_PROMOTION_GATE: 4   KNOWLEDGE_VAULT: 1
```

Every object in this manifest has a corresponding ledger entry (or several
— e.g. HASH fires once for "stored", once for "observation created";
CANDIDATE_RETRIEVAL fires once per provider call plus once per candidate).
