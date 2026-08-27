# Discovery Report — FORGEWORLD Perception Gateway (PROOF-001)

Date: 2026-08-18
Author: Claude Code, on behalf of the repository operator
Canonical root: `jamdav688y-source/forgeworld-runtime`
Working branch: `claude/perception-gateway`, built by merging
`claude/forgeworld-whatsapp-membrane-sj47yn` and
`claude/forgeworld-authority-separation` — see "Branch topology" below for
why both, and why neither is `main`.

## Branch topology (checked before anything else)

`main` (`8095449`) does not contain any of the systems this mission names
("Mission Control," "Execution Ledger," "Knowledge Vault," "Retrieval
Governance," evidence gates, approval policies). Two *unmerged sibling
branches* of `main` — neither merged into the other, neither into `main`
— each build part of what this mission needs:

- `claude/forgeworld-whatsapp-membrane-sj47yn` (3 commits, 2026-08-18):
  a governed inbound/draft/approval pipeline for a hypothetical WhatsApp
  channel. Introduces the `whatsapp/` package: flat-file jsonl ledgers
  (`whatsapp/src/ledger.py`), an authority-tier matrix
  (`whatsapp/src/authority.py` + `whatsapp/governance/05_AUTHORITY_MATRIX.md`),
  a human-approval workflow (`whatsapp/src/approval.py`), a hand-rolled
  schema-validation pattern (`whatsapp/src/schema.py`), a deterministic
  rule-based classifier (`whatsapp/src/classify.py`), and a phone-first
  CLI (`whatsapp/src/cli.py`, `whatsapp/scripts/forge-whatsapp`). Its own
  `whatsapp/governance/00_DISCOVERY_REPORT.md` confirms explicitly that
  almost none of "Mission Control," "Execution Ledger," "Reality Learning,"
  or "Retrieval governance" existed before that mission either — they were
  built minimal-and-new, sized to what the repo actually had.
- `claude/forgeworld-authority-separation` (5 commits, 2026-08-13): the
  `governance/` Python package — `AuthorityState` (`DENIED, ALLOWED,
  ALLOWED_LOCAL, ALLOWED_BOUNDED, REQUIRES_APPROVAL, HUMAN_ONLY,
  UNAVAILABLE, UNKNOWN`), `EvidenceState` (`UNKNOWN, OBSERVED, SUPPORTED,
  VALIDATED, INSTITUTIONALIZED`), `promotion.can_promote()` returning a
  `PromotionDecision`, an audit-event log, and a self-escalation guard.
  Built by this same session for an unrelated incident (a GitHub tag-push
  403), but its vocabulary is a near-exact match for this mission's
  "evidence gates," "Human Promotion Gate," and required `PromotionDecision`
  object — closer, in fact, than `whatsapp/`'s own tier system, which is
  hand-tuned to WhatsApp send actions (`send_pricing`, `mass_outreach`, …).

Both branches share `main` as their sole merge-base and touch disjoint
files (`whatsapp/**` vs. `governance/**`, `execution/**`, `schemas/**`,
`tests/governance/**`), so `claude/perception-gateway` was created by a
clean, conflict-free `git merge` of both — confirmed by running both
existing test suites (60 whatsapp + 60 governance = 120 tests) immediately
after the merge, before writing a single line of new code, all passing.

**This is the concrete meaning of "reuse the canonical repository runtime"
for this mission: neither prior branch alone was that runtime; the merge
of both, verified still-green, is.**

## Inventory of existing components relevant to this mission

| Mission concept | Existing repo equivalent | Reuse decision |
|---|---|---|
| Event Bus | `events/events.log` + `log_event.sh` (single global log); `whatsapp/src/ledger.py` (typed, path-parameterized jsonl append/read with file-locking) | Reused directly: `perception/src/pipeline.py` imports `whatsapp.src.ledger.append/read_all/find` verbatim — zero new file-locking or jsonl logic written |
| Execution Ledger | `whatsapp/ledgers/execution_ledger.jsonl` (file) + `whatsapp/src/ledger.py::EXECUTION_LEDGER` (path constant) | Reused literally: every pipeline stage transition in this mission is appended to the **same** `whatsapp/ledgers/execution_ledger.jsonl`, not a new parallel ledger, using the same `ledger.append()` function |
| Approval policies / Human Promotion Gate | `whatsapp/src/approval.py` (decision-recording pattern: approve/reject/escalate/request_more_evidence, terminal-state locking) + `governance/promotion.py::can_promote()` (independent authority+evidence gate, exact `PromotionDecision` shape this mission requires) | Both reused: promotion decisions are recorded with the same terminal-state-locking discipline as `whatsapp/src/approval.py` (a decided proposal cannot be re-decided), and the actual allow/deny logic **is** `governance.promotion.can_promote()`, imported directly, not reimplemented |
| Evidence gates / evidence classification | `governance/evidence.py::EvidenceState` (`UNKNOWN → OBSERVED → SUPPORTED → VALIDATED → INSTITUTIONALIZED`) + `governance/evidence.py::current_evidence_state()` (multi-source corroboration escalates OBSERVED→SUPPORTED) | Reused directly: `perception/src/evidence.py` imports `governance.evidence` rather than defining a second evidence vocabulary. `whatsapp/src/classify.py`'s `evidence_sufficiency` (sufficient/partial/insufficient) is a *different*, narrower concept (can we draft a reply right now) and is not reused here — reusing it would have been the wrong kind of reuse, forcing an unrelated vocabulary onto a different problem |
| Capability check vs. authority check | `governance/authority.py::evaluate_authority()` (never returns ALLOWED for an unknown capability) + `capabilities/discover.py::probe_one()` (reachability probing: command/env/network/self/manual) | Reused directly: `perception/src/registry.py` calls `capabilities.discover.probe_one()` unmodified for connector-profile reachability; `governance.authority.evaluate_authority()` is the single authority check for every mutating perception action |
| Registries / connector profiles | `capabilities/registry.json` (id/kind/provider/check/tags/cost shape) | Pattern reused, new file: `perception/registry.json` uses the **identical JSON shape**, because it registers a semantically different domain (candidate-retrieval sources: reverse-image search, OCR engine, platform lookup — not AI-agent tools for the operator's own productivity). Forcing these into `capabilities/registry.json` itself would have conflated two different registries under one name; keeping the shape identical and reusing the same probe function is the correct level of reuse |
| Governed ingestion / CLI / Mission Control | `whatsapp/src/cli.py` + `whatsapp/scripts/forge-whatsapp` (phone-first command surface, same `scripts/forge-*` convention as `scripts/forge-capture.sh`, `scripts/forge-route.sh`, …) | Pattern and package structure reused: `perception/src/cli.py` + `perception/scripts/forge-perception` follow the identical argparse/ledger-only/no-heavy-processing-in-the-CLI structure. This *is* Mission Control for this mission, per the same reasoning the WhatsApp discovery report used — no dashboard exists or is built |
| Retrieval-governance engine | `whatsapp/governance/00_DISCOVERY_REPORT.md`'s own finding: "none exists; `evidence_sufficiency` is a placeholder contract, not a real retrieval layer" | Confirmed still true. This mission is what actually builds source corroboration for the first time — `perception/src/corroboration.py` is new, sized to a rule-based/deterministic-first implementation matching `whatsapp/src/classify.py`'s own stated philosophy ("classification decisions gate real consequences… rule-based by design… extension point for AI-assisted classification, not wired in this increment") |
| Knowledge Vault | none anywhere in the repository, any branch | New, minimal: `perception/ledgers/knowledge_vault.jsonl`, written to **only** by a human-decided `PromotionDecision` with `decision == "PROMOTED"` — never by pipeline code directly. See `perception/src/promotion.py` |
| Schema/migration pattern | `whatsapp/src/schema.py` (hand-rolled validation against a JSON Schema file, no `jsonschema` package dependency — none is available and the repo has no lockfile/dependency story) | Pattern reused exactly: `perception/src/schema.py` follows the same `new_x()` + `validate()` + `REQUIRED_FIELDS` + enum-set structure, one function pair per required object |
| Phone capture interface | `scripts/forge-capture.sh`, `whatsapp/scripts/forge-whatsapp` | Reused convention: `perception/scripts/forge-perception ingest <path>` is the phone-usable capture command — see the Termux workflow in `perception/reports/proof_001_execution_report.md` |
| Image processing (OCR / perceptual hash) | none anywhere in the repo | New, and deliberately dependency-free: no `Pillow`/`pytesseract` import anywhere in `perception/src/`, matching `whatsapp/src/schema.py`'s explicit reasoning ("not available in this environment and the rest of the repo has no dependency-management story"). `perception/src/imaging.py` is a from-scratch, stdlib-only (`zlib`, `struct`) PNG decoder, sized to what PROOF-001 actually needs |

## What was explicitly NOT built (matching the WhatsApp mission's own discipline)

- **No live OCR or reverse-image-search provider is wired to a real network
  call.** `perception/src/ocr.py` and `perception/src/retrieval.py` define
  a provider-neutral interface and ship one **deterministic, offline**
  reference implementation each, exactly as `whatsapp/src/classify.py`
  ships a deterministic classifier with a documented, unwired extension
  point for `router/mission_router.py`-routed AI assistance. No API keys
  exist anywhere in this repository for any image-search/OCR vendor; wiring
  one in without credentials would only be able to fail, so it isn't
  wired.
- **No dashboard.** Same reasoning as the WhatsApp mission: Mission
  Control is the CLI.
- **No new database, message queue, or hosted service.** Flat jsonl
  ledgers, consistent with everything else in this repository.

## Fixture discrepancy — disclosed, not worked around

The mission brief specifies "the supplied screenshots corresponding to
1554.png and 1555.png." A full filesystem search
(`find / -iname "1554*.png" -o -iname "1555*.png"`) found **no such
files anywhere in this environment.** The only user-supplied image
present at all is one unrelated phone screenshot from earlier in this
same session (`1477.png`, a real Android screenshot of this repository's
own Pocket Cortex app). This mirrors an established pattern in this
session (a previously "attached" `1455.mp4` also did not exist in this
environment) and is disclosed here rather than silently substituted.

Two things are true simultaneously, and this report keeps them separate:

1. **The mission's acceptance criteria explicitly sanction and require**
   deterministic offline fixtures with mocked provider responses for the
   test suite — this is not a workaround, it is the stated requirement.
   `perception/fixtures/` contains two synthetic, from-scratch-generated,
   near-duplicate PNGs (deliberately **not** named `1554.png`/`1555.png`,
   so nothing here is mistaken for the specific missing supplied files)
   plus deterministic mocked provider-response fixtures.
2. **Proof 001's end-to-end execution report additionally runs the real
   pipeline against the one genuinely real, genuinely available image**
   (`1477.png`), copied into the repository through the same governed
   ingestion mechanism used for the synthetic fixtures, as bonus
   real-world evidence — clearly labeled throughout as a substitution,
   never presented as if it were the named files.
