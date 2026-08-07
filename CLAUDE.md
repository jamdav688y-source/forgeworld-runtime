# Context Integrity Gate

This is a mandatory execution gate, not an optional diagnostic:

```
OPERATOR REQUEST -> CONTEXT INTEGRITY GATE -> CONTEXT VERIFIED -> Evidence Retrieval -> Planning -> Execution
                                            -> CONTEXT MISMATCH -> BLOCK EXECUTION
```

Before making any code change in this repository (repair, refactor, patch,
migration, or any task premised on "file X does Y" / "module X exports Y"),
declare the intent and run the gate:

```
python3 scripts/forge_context_gate.py --project <subproject-dir> \
  --intent "modify: <file the task is about>" \
  --assert-import "from <module> import <name>[, <name>...]"
```

`--intent` accepts `modify:` / `create:` / `delete:` / `read:` (a bare path
defaults to `modify`) and is verified against reality: file existence,
git-tracked state, current branch, repository root.

If it exits non-zero (`CONTEXT_MISMATCH` or `BLOCKED`), stop. Do not create
replacement functions, compatibility wrappers, or missing files to make the
mismatch go away — report the mismatch instead. This exists because of a
real incident (see `diagnostics/incidents/VALIDATE_SEARCH_IMPORT_FAILURE.md`):
a repair task was handed a traceback describing a file and an API that
didn't exist anywhere in the repository actually being worked on. The gate
catches that in about a second instead of a full investigation.

The JSON report (`--json` / `--json-out`) is versioned: `"schema":
"context_gate.v1"`. Field names are stable within a schema version — safe
for other tooling to parse directly instead of the human-readable summary.

See `scripts/forge_context_gate.py --help` for the full flag set
(`--target-file`, `--require-file`, `--require-dir`, `--require-tool`,
`--scan-whole-project`, `--json`, `--json-out`).

Deliberately not yet in `governance/`/`doctrine/`: this stays an
operational capability until it's been exercised across multiple
repositories and workflows. Elevate it to the constitutional layer only
once it's proven stable.
