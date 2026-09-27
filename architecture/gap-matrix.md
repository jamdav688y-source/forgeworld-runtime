# ForgeWorld Gap Matrix

Primitive-by-primitive classification against Section 3 of MISSION_ID:
FORGEWORLD-CONTINUITY-FABRIC-001. Classification values:
`PROVEN_WORKING`, `PRESENT_UNVERIFIED`, `PARTIAL`, `DUPLICATE`, `STALE`,
`MISSING`, `BLOCKED`. A primitive is never marked `PROVEN_WORKING` on the
strength of source code alone — only on a passing test observed in this
session, or an explicit note that the evidence is transitive (exercised
indirectly by another suite).

| # | Primitive | Classification | Evidence |
|---|---|---|---|
| 1 | PermanentMemory | **PARTIAL** | No unified, typed memory primitive exists. Narrow, durable ledgers exist for specific domains and are proven for those domains only: `artifact_handoff/lineage_store.py` (12/12 passing), `evidence_envelope/envelope.py` mission ledger (native tests `PRESENT_UNVERIFIED` here — no pytest — but its `_FileLock`/`_atomic_write_bytes`/`validate_mission_id` primitives are exercised transitively and pass via `lineage_store`'s 12 tests). No memory-type taxonomy (episodic/semantic/project/relationship/commercial/decision/procedural/working) exists anywhere. `memory/` (root) is **STALE**: three text files, zero code. |
| 2 | ContextCompiler | **MISSING** | No code anywhere constructs a bounded working context from a memory corpus. Nothing to cite. |
| 3 | IdentityFabric | **PARTIAL** | `fabric/interface.py::NodeIdentity` (PC_NODE/PHONE_NODE, validated via `evidence_envelope.validate_mission_id`) is real and **PROVEN_WORKING** (exercised across 48 passing fabric tests) but covers exactly two node types and nothing about model/agent/session identity. |
| 4 | EventFabric | **MISSING** (as specified) / raw materials **PARTIAL** | No typed event log with the candidate classes (CAPTURED/INGESTED/.../REVOKED), dedup, or replay-safety exists. Raw materials that could feed one: `capabilities/history.jsonl`, `router/decisions.jsonl` (plain append, no lock/atomicity), `FabricReceipt.correlation_id`/`causation_id` (`fabric/interface.py`, **PROVEN_WORKING**, deterministic-receipt tests pass). `events/` (root) is **STALE**: one log file, zero code. |
| 5 | CapabilityGraph | **PARTIAL** | `capabilities/registry.json` + `capabilities/discover.py` is a real, tested (14/14) capability *registry* with a rich per-capability schema prototype (`forgeworld_mobile_research` entry carries purpose/inputs/outputs/locality/dependencies/external_effects/failure_state/evidence_provenance/validation_state — see `capability-map.md`). It is a flat registry, not a graph: no compatible/incompatible/supersession edges, no confidence field, no lifecycle state (DISCOVERED→...→PROMOTED). `fabric/interface.py::CAPABILITIES` is a second, simpler runtime dispatch dict (id→provider), unintegrated with the registry. |
| 6 | CapabilityResolver | **PROVEN_WORKING** (narrow) | `router/mission_router.py::score_capability()`/`route()` (deterministic, tag+reachability+cost scoring) and `artifact_handoff/interface.py::route_to_capability()` both resolve one capability_id for one required-tag-set, exercised by passing tests (21/21, 19/19). Resolves a single capability, never composes a multi-step plan. |
| 7 | SkillRegistry | **PARTIAL** | `content_readers/interface.py::READERS` and `fabric/interface.py::CAPABILITIES` are both working, tested (25/25, 19/19) registered-adapter dicts — real but minimal (id→callable), no version field, no schema beyond what each module hand-rolls. |
| 8 | WorkflowCompiler | **MISSING** | No code composes more than one capability for one objective. `fabric`'s transfer-then-capability-request sequence is a hardcoded two-step flow, not compiled from an objective+constraints. |
| 9 | CapabilityRecombinationEngine | **MISSING** | No code asks "what's newly reachable" or auto-discovers composable pairs. Manual recombination has happened by hand this program (`fabric.capabilities.ContentReadCapability` composes `content_readers`+`fabric`; `fabric`'s PC-side processing reuses `artifact_handoff.handoff()`) but there is no engine that does this systematically. |
| 10 | ForgeSentinel | **MISSING** | Zero adversarial-risk-analysis code exists anywhere in this repository. Domain-narrow adversarial defenses exist and are proven (`artifact_handoff/zip_unpack.py`'s path-traversal/zip-bomb/symlink defenses, 21/21 passing; `fabric/tcp`'s message-size/authkey/allowlist/one-shot-listener hardening, 12/12 passing) but neither is a general Sentinel, and neither feeds a shared disposition (ALLOW/CHALLENGE/HOLD/ESCALATE/DENY/REQUIRE_HUMAN_REVIEW) vocabulary. |
| 11 | GovernanceEngine | **PARTIAL** | `evidence_envelope/envelope.py`'s BRONZE→SILVER→GOLD lifecycle plus `record_promotion_authority()` (deliberately does **not** auto-flip promotion status) is a real, working governance pattern (native tests unrunnable here — `PRESENT_UNVERIFIED` — but its primitives are transitively proven via `lineage_store`). `fabric/interface.py::authority_permits()` is a second, much simpler governance gate (static allowlist check), **PROVEN_WORKING** (48 passing tests). The two are not unified. |
| 12 | AuthorityVerifier | **PARTIAL** | `evidence_envelope.py::AuthorityVerificationRequest`/`VerifiedAuthority` define a structured, credential-free attestation *contract* (**PRESENT_UNVERIFIED** here, no pytest) but leave the actual verification decision to an external caller — no concrete verifier implementation exists in-repo. `fabric.authority_permits()` **is** a concrete, tested, but minimal verifier: exact-match-in-allowlist only. |
| 13 | ExecutionFabric | **PARTIAL** | Three separate, each individually **PROVEN_WORKING** execution surfaces exist and do not share an abstraction: `local_inference.run_inference()` (18/18), `content_readers.read_content()` (25/25), `fabric.process_remote_capability_request()` (48 across fabric suites). GPT/Codex/Claude Code are not wired as invokable providers anywhere in code — they are the agents doing the work, not yet a callable surface. |
| 14 | EvidenceLedger | **PARTIAL** | Four separate durable ledgers exist, each proven for its own domain: `evidence_envelope` (mission evidence), `artifact_handoff.lineage_store` (artifact provenance, 12/12), `evidence_envelope.trajectory` (run comparison, native tests unrunnable here), `fabric.FabricReceipt` (per-transaction receipt, deterministic-id tests pass). Not unified; a real recombination candidate. |
| 15 | CapabilityPromotionGate | **MISSING** (for capabilities specifically) | The mission-lifecycle promotion gate in `evidence_envelope` is a proven *pattern* for what this should look like, but nothing in this repository ever moves a *capability* through DISCOVERED→CANDIDATE→...→PROMOTED. `capabilities/registry.json` entries have no lifecycle-state field at all today. |
| 16 | DeviceTransport | **PARTIAL** | `fabric/loopback/` (same-machine process boundary, 17/17) and `fabric/tcp/` (real TCP/AF_INET, 12/12, **loopback-bound in this sandbox only**) are real, tested transport adapters. The physical phone↔PC hop is separately, physically demonstrated only at the raw-TCP-packet level (`nc`, outside ForgeWorld code) — **BLOCKED** for the application-level fabric specifically, on: (a) the TCP fabric code not yet existing in the physical Windows checkout, and (b) no physical round trip yet attempted with it once it does. `forgeworld-mobile-research/` is a real phone-side capture app, entirely unconnected to `fabric/`. |
| 17 | Synchronization/Reconciliation | **PARTIAL** | A concrete, evidence-preserving reconciliation *procedure* was produced (archive + SHA-256 manifest + guarded PowerShell script) in the prior mission, but it is a one-off manual procedure, not reusable infrastructure, and its completion on the physical Windows checkout is unconfirmed. |
| 18 | ProviderRegistry | **PARTIAL** | `capabilities/registry.json` (reachability-only provider entries: `claude_code`, `chatgpt`, `local_llm`, ...) and `local_inference`'s `LocalInferenceProvider` Protocol (invocation-capable, `OllamaProvider` the one adapter) are both real and tested, but are two separate registries — the reachability registry doesn't know which of its entries are actually invokable, and vice versa. |
| 19 | Relationship/CommercialState | **MISSING** | No OBSERVED→...→EXPANSION/REFERRAL state machine exists as code anywhere. `relationships/`, `reputation/` (root) are **STALE** text logs with zero code. `forgeworld-mobile-research`'s `CREATE_COMMERCIAL_PROOF_BRIEF`/`CREATE_CUSTOMER_DEMONSTRATION_BRIEF` are prompt-template *names* only, not state-machine code. |
| 20 | HumanApprovalInterface | **MISSING** (as an interface) / **PARTIAL** (as a data contract) | No interactive approval surface exists. `evidence_envelope.record_promotion_authority()` and `fabric.AuthorityContext.granted_by` both *record* that a human/policy granted something, but nothing prompts for or collects that grant interactively. |

## Duplicate/parallel implementations (not yet harmful, but unrecombined)

Four unintegrated capability-listing mechanisms (`capabilities/registry.json`,
`local_inference` provider Protocol, `content_readers.READERS`,
`fabric.CAPABILITIES`) and four unintegrated durable ledgers (listed under
#14 above). None currently conflicts with another — they occupy disjoint
code paths — but this is exactly the kind of accumulation Section 7's
CapabilityRecombinationEngine is meant to eventually resolve, not by
deleting any of them, but by discovering how they compose.

## Governance risks (live, disclosed, unremediated)

1. **`AuthorityContext.expires_at` is never evaluated.** `fabric/interface.py::authority_permits()` checks only `capability_id in context.granted_capability_ids` — an expired grant currently still passes. This directly risks the mission's own non-negotiable invariant: *"Historical authorization MUST NOT silently become current authority."* Confirmed by reading `authority_permits()`'s full body; no test exercises expiry because there is nothing to exercise.
2. **`fabric/loopback/pc_node_server.py` contains an unconditional `TEST_HOOK` message kind** (`"die"` kills the process, `"sleep_ms"` stalls it), reachable by anyone who can open a connection to it, gated only by the transport-level authkey, never by `AuthorityContext`. Disclosed in the prior mission's Phase 4 audit as low-severity because the script is only ever spawned by this repo's own test suite today — but it is unremediated, and the risk grows the moment anything reuses that script outside a test harness. `fabric/tcp/pc_node_server.py` (the hardened, network-facing sibling) does **not** have this hook — the loopback variant does.
3. **`fabric/capabilities.py` unconditionally registers `echo_mock`** (a capability with no real authority or content check beyond echoing byte counts) alongside `content_read` on import. The TCP server explicitly pops it from the registry after import; the loopback server does not.

## Memory risks

No general memory primitive exists yet (see #1), so there is currently
nothing for the "observation != authority" risk to act *on* at scale — the
risk is latent, not active. Within the code that does exist, the
NOT_EVIDENCE/NOT_PROMOTED/NOT_VALIDATED fixed-property pattern is
consistently and correctly applied everywhere a result object is returned
(`Manifest`, `ContentReadResult`, `InferenceResult`, `RemoteCapabilityResult`,
`FabricReceipt`) — this is a genuine strength to preserve, not rebuild, when
a general PermanentMemory primitive is eventually designed.
