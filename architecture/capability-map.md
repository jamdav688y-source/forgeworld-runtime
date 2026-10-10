# ForgeWorld Capability Map

See `gap-matrix.md` #5–#9, #13, #15, #18 for classifications.

## The capability registry (closest existing analogue to Section 4's CapabilityGraph)

`capabilities/registry.json`, loaded/probed by `capabilities/discover.py`.
Twelve entries today: `claude_code`, `chatgpt`, `local_llm`, `desktop_runtime`,
`python`, `git`, `github`, `zapier`, `gmail`, `google_drive`, `airtable`,
`forgeworld_mobile_research`. Every entry has: `id`, `kind`, `provider`,
`check` (reachability probe spec), `tags`, `cost` (five-axis: dollar,
latency, tokens, attention, complexity). The `forgeworld_mobile_research`
entry additionally carries the richer schema this mission's Section 4 asks
for — `purpose`, `inputs`, `outputs`, `locality`, `dependencies`,
`external_effects`, `failure_state`, `evidence_provenance`,
`validation_state` — added deliberately as a prototype contract for future
entries, not yet backfilled onto the other eleven.

**Missing from every entry, including the prototype:** a `version` field,
a `lifecycle_state` (DISCOVERED/CANDIDATE/TESTED/EXECUTED/VERIFIED/
REPEATED/ADVERSARIALLY_TESTED/PROMOTED/DEPRECATED/REVOKED), a `confidence`
score, `compatible`/`incompatible`/`supersedes` relationships to other
capabilities, and any link to the *test evidence* that would justify a
lifecycle state.

## Reachability vs. invocability — two different registries

`discover.py::probe_one()` answers "is this reachable" (PATH_FOUND /
LAUNCH_VERIFIED / IDENTITY_VERIFIED / VERSION_VERIFIED / VERSION_UNSUPPORTED
/ UNREACHABLE / TIMEOUT / IDENTITY_MISMATCH — a real, tested state
vocabulary, 14/14 passing). It does **not** answer "can I invoke this and
get a structured result." That's a separate concern, handled by three
independent, un-unified invocation surfaces:

| Invocation surface | Registry | Tested |
|---|---|---|
| `local_inference.LocalInferenceProvider` Protocol | not `capabilities/registry.json` | 18/18 |
| `content_readers.READERS` dict | not `capabilities/registry.json` | 25/25 |
| `fabric.CAPABILITIES` dict | not `capabilities/registry.json` | 48 (across fabric suites) |

None of these three know that `capabilities/registry.json` exists; none of
`capabilities/registry.json`'s entries carry a pointer into any of the
three. A capability can be "reachable" per `discover.py` and simultaneously
have no way to actually be invoked through any of the three real invocation
surfaces, or vice versa (`content_read`/`echo_mock` are invocable via
`fabric.CAPABILITIES` but have no corresponding `capabilities/registry.json`
entry at all).

## Resolution (CapabilityResolver, Section 4/6)

`router/mission_router.py::score_capability()` — pure function, deterministic:
confidence = weighted(reachability, task_fit, output_quality,
historical_evidence) minus cost penalty. `route()` wraps this with
reachability probing and decision logging (side-effecting, writes
`router/decisions.jsonl`). `artifact_handoff/interface.py::route_to_capability()`
is a second, independent resolver reusing `score_capability()` directly
(bypassing `route()`'s side effects) — this is the *better* pattern
(pure-function reuse, no unwanted log writes) and should be the template
for any future resolver, not `route()` itself.

**A real, previously-caught defect, now fixed:** an earlier version of
`artifact_handoff.route_to_capability()` selected any *reachable*
capability regardless of tag relevance (a cheap, irrelevant capability like
`git` could outscore a relevant-but-unreachable one). Fixed by requiring
`task_fit > 0` in addition to reachability. Documented here because it is
exactly the kind of failure Section 6 ("do not promote based merely on
existence of code") warns about — the code existed and looked correct
until an adversarial test proved otherwise.

## Composition and recombination (Sections 5, 7)

No `WorkflowCompiler` exists. The closest real precedent for *manual*
recombination: `fabric/capabilities.py::ContentReadCapability` composes
`content_readers.read_content()` inside the `fabric` capability-dispatch
surface — one capability built by wiring two existing, unmodified ones
together, then tested as its own unit (part of the 48 passing fabric
tests). This is evidence that composition-by-reuse works in this codebase;
there is no engine that does it automatically.

## Promotion (Section 6, gap-matrix #15)

No capability in `capabilities/registry.json` has ever been marked
`PROMOTED` or any other lifecycle state — the field doesn't exist. The
*pattern* for what a promotion gate should look like already exists and is
proven elsewhere: `evidence_envelope.record_promotion_authority()`
deliberately records that authority was attested **without** auto-flipping
promotion status. Reusing this exact discipline for capabilities (record
that a capability passed a promotion gate step, without any code path that
auto-promotes on test-pass alone) is the natural template for Section 6.
