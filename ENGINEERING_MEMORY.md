# ENGINEERING_MEMORY.md

Decisions, reasoning, and fixes from building `substrate-runtime/`. Read
before re-deriving something already decided here — or before "fixing" a
documented simplification.

## Decisions

**Native Android (Kotlin), not React Native/Flutter/backend-only.**
User's explicit choice, matching this repo's existing Termux/Android-phone
framing (§ MISSION_LOG.md, MICRO_SUBSTRATE_RUNTIME_V1). Consequence: the
Android-specific module (`app/`) cannot be built or tested in this sandbox
(no Android SDK). Mitigated by splitting all pipeline logic into a
zero-Android-dependency `core` module that a plain JDK can build and test.
This split is why `core`/`app` exist as separate Gradle modules at all —
it's not premature layering, it's what made real verification possible here.

**Full spec attempted in one pass, not a vertical slice.**
User's explicit choice, after being asked. Consequence: `app`'s governance
gating, commercial analysis, and visualization all exist, but only `core`'s
logic has been exercised by tests — the Room/Compose wiring is
best-effort-correct, reviewed but not compiler-verified.

**All 12 pipeline stages run unconditionally, including for REJECTed events.**
The mission spec states Runtime Invariants #4 ("every event creates
evidence") and #6 ("every event becomes searchable memory") without
exception. Rather than special-case rejected events out of evidence/memory
creation, `EventPipeline.submit()` is strictly linear — no early return.
`ExecutionOutcome.kind` currently has no consumer beyond being recorded, since
no external action (build trigger, notification, etc.) is wired up. This is a
deliberate reading of an underspecified point in the mission text, not an
oversight — flag it if a future mission wants REJECT to actually halt
persistence.

**Governance violations are `blocking: Boolean`, not uniformly fatal.**
A literal reading of "no path may let an event proceed while violations
exist" would make low-confidence classification (an extremely common,
expected case for freeform text) reject nearly everything. Instead,
`GovernanceValidator` distinguishes hard violations (blank actor, empty
content, self-dependency — reject) from soft ones (low classification
confidence, evidence-already-exists — hold/inform but proceed). This is the
difference between `ExecutionDecisionKind.REJECT` and `.HOLD` in
`ExecutionDecisionEngine`.

**Vector search is bag-of-words TF + cosine similarity, not full TF-IDF.**
No corpus-wide document-frequency statistics are maintained — keeping memory
retrieval deterministic, dependency-free, and fully offline (no embedding
model, no network call) at the cost of not down-weighting rare-but-common
words as well as real TF-IDF would. A small fixed stopword list (see "Bugs
found and fixed" below) covers the worst case. If retrieval quality becomes a
real problem, the next step is corpus IDF, not switching to an embedding API
— that would break the offline-first requirement.

**Deterministic node/edge ids everywhere (`domain:<TYPE>`, `topic:<slug>`,
`edge:<TYPE>:<from>:<to>`).**
This is what makes reinforcement (repeated activation strengthening one
edge/node) work instead of the graph growing a new node/edge per event. It
also directly satisfies the FORGEWORLD Constitution's "no duplicate records"
mandate — the first place in this repo's history that rule is actually
enforced rather than stated.

**Topic-node consolidation is text-literal, not semantic clustering.**
The topic node id is a slug of either the first non-project tag or the first
six words of cleaned text. Two differently-worded events about the same real
subject will land on two different topic nodes (connected only via a SEMANTIC
edge if their bag-of-words vectors are similar enough). True concept
clustering (e.g. clustering topic nodes together after the fact) was
explicitly scoped out — see the corrected test in
`EventPipelineTest.kt` ("repeating the same event reinforces...") which was
originally written assuming cross-sentence consolidation and had to be
rewritten once that assumption was found false. Don't re-introduce that
assumption without actually implementing clustering.

## Bugs found and fixed during this build

1. **Toolchain mismatch.** `core/build.gradle.kts` initially requested
   `jvmToolchain(17)`; sandbox only has JDK 21 with toolchain
   auto-provisioning disabled. Fixed by requesting `jvmToolchain(21)`. If
   this project is later built where JDK 17 is the standard, revisit —
   Android's Java 17 `compileOptions` in `app/build.gradle.kts` is unrelated
   and unaffected.

2. **Stopwords dominating cosine similarity.** `VectorIndexTest`
   ("unrelated text has low similarity") failed: two genuinely unrelated
   sentences shared only the word "the" (appearing twice in each), which
   after normalization was enough to push cosine similarity to ~0.42 against
   a proper genuinely-unrelated result. Root cause: `vectorize()` had no
   stopword filtering. Fixed by adding a ~25-word fixed stopword list.
   Documented as a deliberate simplification (not full IDF) rather than
   overclaimed as complete.

3. **`#project:x` tag not recognized.** The original `TAG_PATTERN` regex had
   alternatives `#[A-Za-z0-9_-]+` and `project:[A-Za-z0-9_-]+` but not the
   combined `#project:x` form a user would naturally type. The regex matched
   only `#project`, stopping at the colon, so `RelationshipGraphEngine`'s
   `startsWith("project:")` filter never fired and no PROJECT edge was
   created — caught by `EventPipelineTest`'s edge-reinforcement test.
   Fixed by adding a `#project:x` alternative (checked first, so alternation
   doesn't short-circuit on the bare `#tag` case) and stripping the leading
   `#` during normalization so both spellings converge to the same
   `project:x` tag string.

## Things deliberately not built (raised, decided against or deferred)

- **A DI framework (Hilt/Koin).** The object graph is five repositories and
  one pipeline — `SimpleViewModelFactory` + manual wiring in
  `SubstrateApplication` is less ceremony for this size.
- **JSON serialization library for vector storage.** `MemoryEntity` stores
  the term-frequency map as a hand-rolled `key=value;key=value` string
  (`VectorCodec.kt`) rather than pulling in kotlinx.serialization/Gson for a
  `Map<String, Double>` that never needs nested structure.
- **Force-directed graph layout.** Would meaningfully improve the neural
  landscape's readability at scale, but is a separate, sizeable piece of
  work; the current deterministic radial layout satisfies "visualization is
  a direct projection of runtime state" without it.
