# Migration Dry Run — WhatsApp Membrane

**No files were copied, moved, or written outside this repository to produce this document. This is
analysis only, per the promotion mission's explicit "without copying files" instruction.**

## 1. Source file inventory

54 files under `whatsapp/` (full list: `whatsapp/reports/whatsapp_membrane_checkpoint.json`
→ `file_inventory.files`), plus 1 file outside that tree:

- `.github/workflows/whatsapp-tests.yml` — the only governance-critical file that lives **outside**
  `whatsapp/`. A migration that copies only the `whatsapp/` directory will silently leave CI behind
  unless this file is copied too.

Directory shape:

```
whatsapp/
  config.json                 5 governance docs, 1 schema
  governance/                 (6 files)
  schemas/                    (1 file)
  src/                        (18 .py files)
  ledgers/                    (.gitkeep + README only — no real data exists to migrate)
  fixtures/                   (7 sanitized JSON files + README)
  tests/                      (11 .py files, 60 tests)
  scripts/forge-whatsapp      (1 CLI entrypoint)
  runbook/                    (3 files)
  reports/                    (9 files as of this pass, growing)
```

## 2. Proposed destination structure

Unknown — **no canonical destination repository has been established** (see §5 below and
`whatsapp/reports/pre_merge_certification.md` §1/§7). This section can only describe the *shape* of a
plausible destination, not name one:

```
<destination-repo>/
  whatsapp/                   <- identical subtree, copied as-is
    ... (same layout as above)
  .github/workflows/whatsapp-tests.yml   <- copied from repo root, not whatsapp/
```

No collision analysis is possible against an unnamed destination. If/when a destination is named, this
section must be redone against that repository's actual existing file tree before any copy occurs.

## 3. Path and configuration dependencies (collision/portability risks)

A directory copy was previously described (in `pre_merge_certification.md` §7.3) as sufficient because
"there is no repo-root-relative or absolute path baked in anywhere outside" the
`Path(__file__).resolve().parent.parent` pattern. **That description was incomplete and is corrected
here:**

| File | Dependency | Portable? |
|---|---|---|
| `whatsapp/src/draft.py:15` | `MEMORY_LOG = MODULE_ROOT.parent / "memory" / "memory.log"` — reads the **sibling repo-root** `memory/memory.log`, which belongs to FORGEWORLD's own RPG/personal system, not to the `whatsapp/` subtree | **Not portable as-is.** A plain copy of `whatsapp/` into a new repo with no `memory/memory.log` at its root does not crash (`_read_memory_context()` returns `[]` if the file is absent — verified by reading the code, `draft.py:34-37`), but it silently drops the "prior context" input to every drafted response. This is a behavior change, not a crash, and would go unnoticed without this note. |
| `whatsapp/src/classify.py` (docstring only) | Names `router/mission_router.py` and `capabilities/registry.json` as an unwired future extension point | **Not a runtime dependency** — mentioned only in a comment, never imported or called. No portability impact. |
| `whatsapp/src/ledger.py`, `modes.py`, `schema.py`, `draft.py` | `MODULE_ROOT = Path(__file__).resolve().parent.parent` (i.e., wherever `whatsapp/` lives) | **Portable.** Self-relative; works identically at any repo root. |
| All `whatsapp/src/*.py` internal imports | `from . import ...` (relative) and `whatsapp.src.*` / `whatsapp.tests.*` (absolute, assuming `whatsapp/` is importable from the repo root) | **Portable**, provided the destination repo root is on `sys.path` / is the working directory when running `python3 -m whatsapp.src.cli` or the test suite — same requirement as today. |
| `.gitignore` entries `whatsapp/.env*`, `whatsapp/ledgers/*.jsonl` | repo-root `.gitignore`, not inside `whatsapp/` | **Not portable automatically** — a destination repo needs its own `.gitignore` entries added; copying `whatsapp/` alone does not carry this protection over. Flagged as a required manual step, not an automatic one. |
| `whatsapp/scripts/forge-whatsapp` | `REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"` then `cd "$REPO_ROOT"` | **Portable.** Self-relative to wherever the script physically sits; makes no assumption about the repo's name or remote. |

**Corrected collision/dependency count: 1 real behavioral dependency (`memory.log`), 1 required-but-not-automatic
config carryover (`.gitignore`), 1 documentation-only non-dependency. This is a materially more accurate
picture than the prior certification's "no code changes are anticipated" claim, which missed the
`memory.log` read.**

## 4. Secrets/credentials scan (repeated for this dry run, not assumed from the prior pass)

```
$ grep -rEn "(WHATSAPP_ACCESS_TOKEN|WHATSAPP_APP_SECRET|WHATSAPP_VERIFY_TOKEN)[\"']?\s*[:=]\s*[\"'][A-Za-z0-9_\-]{20,}" whatsapp/ --include="*.py" --include="*.json" --include="*.md" | grep -v "fixture\|not-real\|os.environ"
```
Result: no matches. Consistent with the pre-merge certification's finding. No credential would be
carried by a copy — none exists to carry.

## 5. Canonical destination authority check

Per the explicit instruction to verify this without inferring from names, proximity, or convenience:

- **Searched within `forgeworld-runtime` (this repo):** no file declares a canonical business
  repository, registry entry, or authoritative destination for this code. (Full grep in
  `whatsapp/reports/pre_merge_certification.md` §1 and re-confirmed in this pass.)
- **Searched connected repository context:** the operator's GitHub account has six other repositories
  visible to this session's tooling: `ophi-diagnostic-kernel`, `governed-ai-systems`, `Synthetic-Mind-new`,
  `Master-template`, `Control-Plane-invariant-custody-`, `governance-control-plane` (all public). **None
  of these were opened, read, or treated as candidates.** Their names are not evidence — per the explicit
  instruction not to infer a destination from names or convenience, a repository named
  "governed-ai-systems" is not, on that basis alone, established as the canonical destination for this
  code. If the operator has already designated one of these (or any other repository) as canonical, that
  designation was not found in any artifact readable by this session.
- **No operator-provided destination has been given in this conversation or any prior one in this
  session's context.**

**Conclusion: no canonical destination is established by evidence. Migration authority does not exist.**

## 6. Rollback method (for if/when a real migration is later performed)

Not applicable in the same sense as a code rollback, because no migration has occurred. For the record,
once a real migration does happen: the source repository's `whatsapp/` subtree and its git history are
untouched by a copy-based migration (copying doesn't delete the source), so "rollback" reduces to
continuing to use the source repository's copy and treating the destination copy as abandoned — no
destructive step is inherent to this kind of migration.

## 7. Post-migration verification (for if/when a real migration is later performed)

1. `cd <destination-repo> && python3 -m unittest discover -s whatsapp/tests -p "test_*.py"` — expect
   60/60 passing, exit code 0 (same command already verified in this repo, see
   `whatsapp/reports/test_run_evidence.txt`).
2. Confirm `whatsapp/src/draft.py`'s `MEMORY_LOG` dependency has been either (a) deliberately accepted as
   now-always-empty in the new location, or (b) redirected to wherever the destination repo keeps
   equivalent context, per §3 above — this must be a conscious decision, not an unnoticed silent change.
3. Re-add the `.gitignore` entries for `whatsapp/.env*` and `whatsapp/ledgers/*.jsonl` in the destination
   repo before ever running the live webhook receiver there.
4. Re-create `.github/workflows/whatsapp-tests.yml` at the destination's `.github/workflows/` path (it is
   not inside `whatsapp/` and will not be carried by a subtree-only copy).
5. Re-run the same secrets grep from §4 against the destination after copying, before any commit.

## 8. Git history implications

- A plain directory copy (not a `git subtree`/`git filter-repo` extraction) would **not** carry this
  repository's commit history for `whatsapp/` — the destination repo would see the code appear as a
  single new addition, losing the F-01 through F-07 defect/fix history recorded in
  `whatsapp_failure_correction_ledger.md` as git blame/log context (the markdown record itself would
  still transfer as a file, just not as replayable commits).
- If preserving history matters, `git subtree split -P whatsapp -b whatsapp-only` (run against this
  repo, not the destination) followed by pulling that branch into the destination is the standard,
  non-destructive way to carry history — this was not executed, per the "no migration" constraint.
- Either way, this repository's own history (including the FORGEWORLD RPG content) is never at risk from
  a migration: extracting a subtree does not delete anything from the source.
