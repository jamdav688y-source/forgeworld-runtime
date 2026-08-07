# Context Integrity Gate

Before making any code change in this repository (repair, refactor, patch,
migration, or any task premised on "file X does Y" / "module X exports Y"),
run:

```
python3 scripts/forge_context_gate.py --project <subproject-dir> \
  --target-file <file the task is about> \
  --assert-import "from <module> import <name>[, <name>...]"
```

If it exits non-zero (`CONTEXT_MISMATCH` or `BLOCKED`), stop. Do not create
replacement functions, compatibility wrappers, or missing files to make the
mismatch go away — report the mismatch instead. This exists because of a
real incident (see `diagnostics/incidents/VALIDATE_SEARCH_IMPORT_FAILURE.md`):
a repair task was handed a traceback describing a file and an API that
didn't exist anywhere in the repository actually being worked on. The gate
catches that in about a second instead of a full investigation.

See `scripts/forge_context_gate.py --help` for the full flag set
(`--require-file`, `--require-dir`, `--require-tool`, `--scan-whole-project`,
`--json`, `--json-out`).
