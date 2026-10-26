# Pre-Merge Architectural and Security Certification — PR #4

**Scope:** `jamdav688y-source/forgeworld-runtime` PR #4 (`claude/forgeworld-whatsapp-membrane-sj47yn` → `main`)
**Certifier:** Claude Code, in a follow-up review session, independent pass from the implementation session
**No merge performed. No credentials added. No live external action taken.**

---

## 1. Repository ownership determination (from repository evidence only)

**Finding: this repository is not established, anywhere in its own history, as the canonical owner of a
business-customer-data system. It is repeatedly and independently self-declared as a personal
RPG/productivity/research runtime.**

Evidence, in order of weight:

1. `STATUS.md:4` — "Core identity: Persistence-first RPG, simulation, world-building, and diagnostic
   engine."
2. `governance/CONSTITUTION_v3.txt:3` — "FORGEWORLD operates as a governed continuity runtime whose
   purpose is the preservation of causal understanding across time" — a personal-continuity framing,
   with `npc/`, `factions/`, `reputation/`, `quests/`, `rpg/player.json` as first-class system roles, not
   business subsystems.
3. **PR #1** (open, unmerged, `claude/silent-wake-crpg-init-aoqr11`, an independent earlier session)
   states verbatim: *"Documents the full ForgeWorld repo map, confirms it contains no reusable
   game-engine code... recommends a silent-wake/ directory"* for building **The Silent Wake, a CRPG**,
   inside this same repository. A second, independent AI session, with no knowledge of this one,
   reached the same conclusion this certification reaches: the repo's own doctrine is game/personal
   design material, not business infrastructure.
4. `forgeworld-mobile-research/README.md:9-10` (merged, PR #3) — self-describes as "a private,
   offline-first research companion for screenshots... the mobile knowledge-ingestion and
   institutional-memory layer of ForgeWorld," listing its own consumers as "Codex, Claude Code, ChatGPT,
   NotebookLM, LinkedIn, cinema/RPG design" — personal tooling, not a commercial platform.
5. No file anywhere in the repository (searched: all `*.md`, `*.txt`, `*.json` outside `whatsapp/`)
   contains the words "canonical," "business intelligence," "system of record," or "authorized owner" in
   reference to this repo. The one "canonical" hit found (`forgeworld-mobile-research/DATA_MODEL.md:11`)
   refers to a screenshot-image database record, unrelated to WhatsApp or commercial ownership.
6. No `AGENTS.md` or `CLAUDE.md` exists at the repo root declaring project purpose, deployment target,
   or integration ownership.

**Conclusion:** the repository-boundary concern raised is correct and confirmed. This repo's own
declared identity, corroborated independently three separate times (its constitution, an unmerged sibling
PR, and a merged sibling PR), is a solo operator's personal system — not a declared business-intelligence
platform authorized to be the long-term home for real customer PII and commercial WhatsApp messaging.

---

## 2. Dependency classification

Every capability the WhatsApp module needed but that didn't exist in this repo, classified per the
requested taxonomy:

| Mission-assumed dependency | What was built locally | Classification | Rationale |
|---|---|---|---|
| Conversation Ledger | `whatsapp/ledgers/conversation_ledger.jsonl` + `whatsapp/src/ledger.py` | **Duplicated canonical capability** (provisionally) | No canonical ledger exists anywhere in the repo to adapt to, so this isn't an adapter over something real — it's a new implementation that *would* duplicate a real canonical ledger if the business ever gets one elsewhere. Correct short-term choice, wrong long-term location if this repo isn't the canonical root. |
| Execution Ledger | `whatsapp/ledgers/execution_ledger.jsonl` | **Duplicated canonical capability** (provisionally) | Same reasoning as above. |
| Reality Learning Loop / Reality Signal Engine | `whatsapp/ledgers/signal_ledger.jsonl` (append-only, no aggregation/promotion logic) | **Unresolved** | Deliberately left as a raw append log with no promotion engine, per the mission's own rule that no single message may modify capabilities without aggregated, validated evidence. There is nothing to duplicate or adapt — it's an acknowledged gap, not a stand-in implementation. |
| Memory Buffer | reads `memory/memory.log` directly in `whatsapp/src/draft.py` | **Legitimate adapter** | This is the one dependency that actually exists in the repo and is reused, read-only, without modification or duplication. |
| Capability registry / authority engine | `whatsapp/src/authority.py`, `whatsapp/governance/05_AUTHORITY_MATRIX.md` | **Misplaced business capability** | `capabilities/registry.json` + `router/mission_router.py` are real and reused only as a *documented, unwired* extension point for AI-routing (`classify.py`'s trailing docstring) — they were correctly **not** repurposed as a customer-facing authority engine, because they have no concept of customer consequence. But the authority engine that *was* built is real business-governance logic (pricing/discount/contract-adjacent gating) sitting inside a personal-RPG repo's directory tree. It works, and it's correctly scoped, but its *location* is the misplacement, not its design. |
| Commercial opportunity records | `whatsapp/ledgers/opportunity_ledger.jsonl` | **Misplaced business capability** | Same reasoning — this ledger's entire purpose (once populated) is commercial pipeline data (real prospects, deal signals), which is a business system-of-record concern, not appropriately owned by a repo whose own constitution disclaims that role. |
| Notification system | none built | **Unresolved** | Explicitly not built; escalation surfaces only as a ledger flag read by the CLI. Honestly reported as missing in the original evidence package, not silently stubbed. |
| Mission Control interface | `whatsapp/scripts/forge-whatsapp` (CLI) | **Legitimate adapter** | Follows the repo's own existing `scripts/forge-*` convention exactly (same shebang/entrypoint pattern as `forge-route.sh`). This is a correctly-scoped extension of a pattern that already lives in this repo, not a duplicate of a Mission Control system that doesn't exist. |
| Webhook intake, normalization, classification, drafting, outbound gating (`webhook_adapter.py`, `normalize.py`, `classify.py`, `draft.py`, `outbound.py`, `reconcile.py`, `pipeline.py`) | new, channel-specific code | **Legitimate adapter** | These are WhatsApp-protocol-specific mechanics with no canonical-system equivalent to duplicate anywhere. Portable as-is to wherever the canonical business root ends up — they don't encode business data, only protocol/governance mechanics. |

**Net finding:** the *protocol and governance mechanics* (webhook handling, schema, classifier, draft
compiler, authority engine's rule logic, CLI) are portable, correctly-scoped, legitimate engineering that
can move anywhere. The *data-bearing components* (the ledgers themselves, once real customers exist) are
what must not remain long-term in a repo whose own doctrine says it isn't the business's system of
record. This is a **placement problem for data, not a rewrite problem for code**.

---

## 3. Security review

Full line-level review of the diff, including hardening fixes applied during this certification pass
(all 60 tests, including 17 new adversarial tests, pass after these changes — see §5).

| Area | Finding | File:line | Status |
|---|---|---|---|
| Webhook-signature verification | HMAC-SHA256 over raw body, `hmac.compare_digest` (constant-time), correct per live-verified Meta docs | `whatsapp/src/webhook_adapter.py:35-43` | **Sound**, tested against forged/wrong-secret/missing-header |
| Secret handling | Secrets only read from env vars, never hardcoded — **except** `normalize.hash_phone()` fell back to a hardcoded literal salt (`"forgeworld-dev-salt-change-me"`) when `WHATSAPP_ID_SALT` was unset, which would ship a public, zero-protection default that looks configured | `whatsapp/src/normalize.py:21-23` (pre-fix) | **Fixed**: now raises `ConfigurationError` and refuses to derive a contact_id without a real salt (`normalize.py:21-32`). Verified: `test_adversarial.py::TestSaltConfiguration` |
| Replay resistance | Duplicate webhook deliveries deduped on `platform_message_id`; **but** repeated `outbound.send()` calls for the same already-sent draft had no guard — a retried script or race could double-message a real customer | `whatsapp/src/outbound.py` (pre-fix) | **Fixed**: `send()` now checks for an existing `SAFE_AUTOMATION_EXECUTED` record first and short-circuits to `VALIDATED_COMPLETE` (`outbound.py:87-93`). Verified: `test_adversarial.py::TestReplay::test_replaying_an_approved_send_is_idempotent_not_a_double_send` (asserts the fake transport is called exactly once across three attempts) |
| Idempotency | Same finding/fix as replay resistance above | `whatsapp/src/outbound.py:87-93` | **Fixed** |
| Recipient binding | **Confirmed real gap**: `outbound.send(draft, contact_id, to_phone, ...)` never verified `to_phone` actually corresponded to `contact_id` — nothing stopped an approved draft for one contact being delivered to an arbitrary caller-supplied number | `whatsapp/src/outbound.py` (pre-fix) | **Fixed**: added `normalize.hash_phone(to_phone) != contact_id` check, blocking with `BLOCKED_BY_AUTHORITY` (`outbound.py:95-102`). Verified: `test_adversarial.py::TestRecipientBinding` |
| Prompt-injection containment | Message content is passed through `classify.py`/`draft.py` as inert data; no code path executes instructions found in message text; a forged `authority_state`/action embedded in text cannot elevate a decision | `whatsapp/src/classify.py`, `whatsapp/src/authority.py:44-63` | **Sound**, tested: `test_classify.py::test_prompt_injection_text_is_classified_as_data_not_instruction`, `test_authority.py::test_prompt_injection_cannot_elevate_authority` (forged approval-record dict with mismatched action is rejected) |
| Path traversal | No user- or message-derived string is ever used to construct a filesystem path; all ledger paths are fixed module constants; `draft_id`/`contact_id`/`event_id` are UUIDs/hashes used only as dict-filter values, never path components | repo-wide grep, confirmed | **Sound**, no finding |
| Media and URL handling | Media messages are hashed by `media_id` only (`whatsapp/src/normalize.py:_content_hash_for_message`); no attachment is ever downloaded or fetched, no URL is ever dereferenced by this code — eliminates SSRF and malicious-payload-execution vectors by construction | `whatsapp/src/normalize.py` | **Sound by design**; malware/type/size scanning remains an explicit, documented go-live blocker (no live media pipeline exists to scan against) |
| Log/evidence redaction | **Confirmed real gap**: per-item normalization failures stored `str(e)` (e.g. a `ValueError` from `int()` embeds the raw malformed field value) and one path stored a full `traceback.format_exc()` into the durable, potentially-shared execution ledger | `whatsapp/src/webhook_adapter.py` (pre-fix) | **Fixed**: all three error-recording sites now store only `type(e).__name__`, never the exception message or a traceback (`webhook_adapter.py:88-136`) |
| JSONL corruption/concurrency | **Confirmed real gap**: `ledger.append()` had no file locking — concurrent writers (webhook receiver + CLI, or two concurrent webhook deliveries) could interleave partial writes into one corrupted line; `read_all()` raised uncaught `JSONDecodeError` on any corrupted line, crashing every consumer (dedup checks, consent lookups, the approval queue) for the whole ledger, not just the bad record | `whatsapp/src/ledger.py` (pre-fix) | **Fixed**: `append()` now takes an exclusive `fcntl.flock` for the write, `read_all()` takes a shared lock for the read and skips (preserving to a `.corrupt` sidecar file, never silently discarding) any line that fails to parse instead of raising (`ledger.py`, full rewrite). Verified: `test_adversarial.py::TestConcurrency` (8 threads × 50 writes, zero interleaving, zero loss) and `TestLedgerCorruption` (3 scenarios: mid-batch corruption, truncated partial write, empty file) |
| Authorization bypass | `authority.check_send_authorized()` requires a real execution-ledger-sourced `approval_record` with matching `action`; a caller-forged approval dict with the wrong action is rejected; prohibited-tier actions require an explicit `config.json` grant that ships empty by default | `whatsapp/src/authority.py:44-78` | **Sound**, tested: `test_authority.py::test_prompt_injection_cannot_elevate_authority`, `test_prohibited_action_blocked_without_grant` |
| Emergency-stop enforcement | `modes.is_outbound_blocked()` re-reads `config.json` from disk on every call (no caching); checked first in `check_send_authorized()`, before consent/authority-tier logic | `whatsapp/src/authority.py:52-54`, `whatsapp/src/modes.py` | **Sound**, tested: `test_authority.py::test_emergency_stop_blocks_send`, `test_outbound.py::test_emergency_stop_blocks_send_even_when_approved_and_configured`, and new `test_adversarial.py::TestOutboundDuringEmergencyStop` (mid-conversation stop, and stop blocking multiple pending drafts simultaneously) |
| Accidental live-network activation | `outbound._default_http_post` (the only code path that makes a real HTTP call) is only reached if a caller omits `http_post` **and** both `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` are set **and** a human-sourced `APPROVED_AWAITING_SEND` record exists. All 60 tests inject a fake transport. **Separately noted (not a vulnerability, a completeness gap):** the CLI (`whatsapp/src/cli.py`) has no `send` subcommand at all — there is currently no operational path to trigger a real send even after approving via the phone. This is safe (nothing can accidentally fire) but incomplete; flagged for the next-right-move list, not fixed here since adding a send command is a feature decision, not a security fix. | `whatsapp/src/outbound.py`, `whatsapp/src/cli.py` | **Sound** (fail-closed); CI workflow adds an explicit socket-blocking test-runner step as a second independent guarantee (`.github/workflows/whatsapp-tests.yml`) |
| Personal-data exposure in a public repository | **Confirmed and fixed**: the original implementation commit hardcoded the account owner's real email address (`jamdav688y@gmail.com`) as a demo `actor` value in `whatsapp/tests/test_e2e_sandbox.py` (×2) and in `whatsapp/governance/00_DISCOVERY_REPORT.md`'s author line. Not third-party PII, but unnecessary self-disclosure with no functional purpose (any string works as `actor`). | `whatsapp/tests/test_e2e_sandbox.py`, `whatsapp/governance/00_DISCOVERY_REPORT.md` | **Fixed in this commit** (replaced with `"forgeworld-operator"` / "the repository operator"). **Residual, disclosed, not remediated**: the original commit already pushed to the PR branch still contains the email in git history; a history rewrite (force-push) was **not** performed, since that is a destructive operation outside this certification's authorization and the branch may already be fetched elsewhere. If this matters before merge, a maintainer should squash-merge (which drops intermediate history from `main`) or explicitly authorize a rebase. |

---

## 4. Commit/git-history secret and PII scan

Full-history (`git log --all -p`) regex sweep for credential-shaped assignments and phone-number-shaped
strings, repo-wide (not just this PR):

- **No real access tokens, API keys, or app secrets found.** Only fixture literals explicitly named as
  such (`TEST_APP_SECRET = "fixture-app-secret-not-real"`, `secret="not-the-real-secret"`).
- **No real phone numbers found.** All fixture numbers use the `1555...` NANP-reserved-for-fiction range
  or `1000000000000001`-style fake IDs. The one payment-card-shaped number in the repo
  (`4111111111111111`) is the standard, publicly-known Visa test card number, used only inside a
  sensitive-data-*detection* test fixture (`webhook_sensitive_data.json`) — it exists to prove the
  classifier flags it, and is never sent anywhere.
- **One real personal-data item found and fixed**: the operator's own email address, see §3 above.
- **No customer conversations exist** — the repository has never processed live traffic; every ledger
  entry in every test is fixture-derived and lives only in a per-test temp directory, never in the
  committed tree (confirmed: `whatsapp/ledgers/` contains only `.gitkeep` and `README.md`, gitignored for
  the runtime `*.jsonl` files).

---

## 5. CI enforcement added

`.github/workflows/whatsapp-tests.yml` (new) runs on every PR touching `whatsapp/**`:
1. The full 60-test suite via `python3 -m unittest discover`.
2. A second run with `socket.socket` monkeypatched to raise, independently proving no test requires
   network access.
3. A grep-based guard against hardcoded-secret patterns under `whatsapp/`.

This replaces "Checks 0" with an enforceable, required status check once branch protection is configured
to require it (branch-protection configuration itself is a repo-admin action outside this certification's
authorization — flagged, not performed).

---

## 6. Test evidence (post-hardening)

```
$ python3 -m unittest discover -s whatsapp/tests -p "test_*.py"
............................................................
----------------------------------------------------------------------
Ran 60 tests in 0.12s

OK
```

60/60 passing: the original 43, plus 17 new adversarial tests added in this certification pass
(`whatsapp/tests/test_adversarial.py`) covering concurrency, replay/idempotency, ledger corruption,
partial writes, duplicate approvals, forged delivery states, recipient binding, salt configuration, and
emergency-stop-during-active-conversation. No test makes a network call; no test weakens any existing
fail-closed default. `INBOUND=ENABLED_AFTER_VERIFICATION`, `OUTBOUND=DRAFT_ONLY`,
`CAMPAIGN=DISABLED`, `AUTONOMOUS_COMMITMENTS=PROHIBITED` are unchanged.

---

## 7. Terminal recommendation

### `MOVE_TO_CANONICAL_BUSINESS_REPOSITORY`

**Reasoning:** The code itself (§3, §5, §6) is sound, tested, fails closed, and — after this
certification's fixes — has no open findings against the requested security checklist. That is not the
blocking issue. The blocking issue is §1: this repository's own, repeatedly self-declared identity
(three independent corroborations) is a personal RPG/productivity/research system, not a business system
of record. Merging a component that will, once live, hold real customer PII and drive real commercial
messaging into a repo whose own constitution says it exists to preserve "causal understanding" for a
solo operator's RPG world is exactly the repository-boundary failure the review was asked to test for.

No canonical business repository currently exists to move this to — that repository does not exist yet
and creating one is a decision only the operator can make (naming, visibility, access control, billing).
This certification does not create one, per instruction 10/11 (no live external action, no merge).

**Safest procedure, in order:**

1. **Do not merge PR #4 into `main` as-is.**
2. The operator decides where the real ForgeWorld business system of record will live: either (a)
   formally redeclare *this* repository as that system (update `STATUS.md`/`governance/CONSTITUTION_v3.txt`
   to say so explicitly, superseding the current RPG-only identity, and accept that the RPG/game content
   and the business-PII content now share one repo's blast radius — access control, breach scope, and
   backup/retention policy all become shared), or (b) create a new, dedicated repository for the business
   system and treat this PR's `whatsapp/` tree as the seed to migrate there.
3. **Either way, migration is close to a plain directory copy, with one correction**: every file under
   `whatsapp/` reads secrets only from environment variables and writes only to paths computed from
   `Path(__file__).resolve().parent.parent`. **Amendment (found in the later promotion-evidence pass,
   see `whatsapp_migration_dry_run.md` §3):** the claim that no path is baked in outside that pattern was
   incomplete — `whatsapp/src/draft.py` reads the sibling repo-root file `memory/memory.log` (outside the
   `whatsapp/` subtree) for response-drafting context. It degrades gracefully (empty context, no crash) if
   that file is absent post-migration, but this is a real, silent behavior change that needs a conscious
   decision at migration time, not an unnoticed one. Copying the `whatsapp/` directory into a new repo root
   and running `python3 -m unittest discover -s whatsapp/tests` there is sufficient to confirm the tests
   still pass; it does **not**, by itself, confirm the drafting behavior is unchanged. See the dry-run
   document for the full, corrected dependency table before any real migration. No code
   changes are anticipated.
4. Until that decision is made, this PR should be updated to **`KEEP_AS_NONPRODUCTION_REFERENCE_IMPLEMENTATION`**
   status if merged at all: merge only with an explicit, prominent label (e.g. rename the module's
   top banner in `whatsapp/README.md` to state "NON-PRODUCTION REFERENCE — DO NOT CONNECT REAL
   CREDENTIALS HERE") so nobody mistakes its presence in this repo for a decision about where the real
   system lives.
5. Do not begin Meta Business verification, do not set any `WHATSAPP_*` credential, and do not run
   `whatsapp/src/server.py` against real traffic until step 2 is resolved — doing so before the
   repository-boundary question is settled would make the migration in step 3 a real-data migration
   instead of a code migration, with materially higher risk.

This recommendation does not question the implementation quality — it questions only whether this is the
right house for it to live in permanently. That question has a clear, evidence-backed answer: not yet
decided, and not this one by default.
