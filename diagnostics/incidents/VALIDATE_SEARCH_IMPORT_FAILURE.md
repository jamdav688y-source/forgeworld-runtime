INCIDENT: VALIDATE_SEARCH_IMPORT_FAILURE

STATUS:
Closed — non-reproducible in current repository

REPORTED FAILURE:
validate_search.py imports `init_db`, `insert_particle` (and reportedly
`get_db_connection`) from `database.py`. `database.py` does not export
these names, so the import fails immediately.

SCOPE INSPECTED:
- Repository: jamdav688y-source/forgeworld-runtime
  branch claude/pocket-cortex-title-screen-hvf7j8
- Project: forgeworld-mobile-research/
  (database.py last touched at commit 2b8bf70, 2026-08-01)

ROOT CAUSE:
The reported traceback references a file and an API surface that are both
absent from the inspected codebase. The bug report does not describe the
state of this repository.

EVIDENCE:
[x] Repository searched — `grep -RIn` for `init_db`, `insert_particle`,
    `get_db_connection`, and `particle` across the whole repo: zero matches.
[x] Filesystem searched — `find ~ -name validate_search.py` and
    `find /root -iname validate_search.py`: no file found anywhere on the
    machine, under either path convention (`~` resolves to `/root`, not the
    repo, which lives under `/home/user`).
[x] Mounts inspected — `mount` / `/proc/mounts`: nothing mounted under
    `/root`; no symlink or bind mount hiding a second copy of the project.
    The only `database.py` files reachable from `/root` belong to `distlib`
    (a `uv`/`poetry` dependency), unrelated to this project.
[x] Current database API documented — `database.py` exports the class
    `Database` (`connect`, `close`, `cursor`, `execute`, `query`,
    `query_one`, `record_event`, `database_size_bytes`), the factory
    `open_database(settings, project_root, backup_if_exists=False)`,
    `backup_existing_database()`, `utcnow()`, and `SCHEMA_SQL`. No `DB`
    symbol, no top-level `init`, no re-exported `sqlite3`.
[x] No obsolete API references found — every consumer already imports the
    current API: search.py, prompts.py, indexer.py, watcher.py, app.py,
    tests/conftest.py all use `Database` / `open_database` / `utcnow`.
    `python -m py_compile database.py` succeeds.

CONCLUSION:
Bug report belongs to a different repository, branch, or historical
working tree than the one available in this environment. No repair was
made — inventing `init_db`/`insert_particle`/`get_db_connection` shims or
a `validate_search.py` to match the report would have been fabricating a
fix for a codebase that doesn't exist here, not reproducing or resolving
the incident.

NEXT STEP (owner action required):
Confirm which repository/branch/working tree the original Termux
traceback was captured against, and whether `validate_search.py` needs to
be authored fresh here or pulled forward from that other location.
