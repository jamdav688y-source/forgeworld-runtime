# FORGE COMMAND LANGUAGE

FORGE.STATUS
Show current phone node status.

FORGE.CAPTURE
Record new idea, bug, observation, or task.

FORGE.SYNC
Prepare files for Git/laptop transfer.

FORGE.REQUEST_BUILD
Send build request to laptop/Codex workflow.

FORGE.REQUEST_REVIEW
Mark output for ChatGPT review.

FORGE.ARCHIVE
Move obsolete material into archive.

FORGE.EXPORT
Prepare post, image, document, or app export.

FORGE.DISCOVER
Probe every registered capability (claude_code, chatgpt, local_llm,
desktop_runtime, python, git, github, zapier, gmail, google_drive,
airtable) for reachability and write capabilities/state.json.
Run: scripts/forge discover

FORGE.ROUTE
Deterministically route a mission to a capability. Scores reachability,
task-fit, output quality, and historical evidence against dollar/latency/
token/attention/complexity cost, and logs the full decision (selected
capability, alternatives, evidence, tradeoffs) to router/decisions.jsonl.
Run: scripts/forge route --objective "..." --tags tag1,tag2
Optionally gate routing on a capability_negotiation mission first --
routing is skipped entirely (status "queued_capability_gap") if that
mission's requirements aren't met:
Run: scripts/forge route --objective "..." --tags tag1,tag2 --negotiate <mission_id>

FORGE.NEGOTIATE
Capability Negotiation Engine -- runs BEFORE a mission executes, not
after it fails. Compares live-probed capability evidence against a
named mission's declared requirements (capability_negotiation/missions.py),
classifies every gap specifically (missing_connector, missing_executable,
missing_filesystem_access, missing_operator_authorization, etc. -- never
a bare "failed"), and publishes CAPABILITY_REGISTRY.json,
CAPABILITY_REPORT.json, CAPABILITY_GAPS.json, OPERATOR_ACTIONS.md, and
CAPABILITY_EVIDENCE.json to capability_negotiation/reports/<mission_id>/.
It cannot invent a capability or force one to AVAILABLE -- every positive
state traces back to a real probe or to live evidence the calling agent
explicitly supplied (e.g. a real ListConnectors result).
Run: scripts/forge negotiate --mission <id> [--live-connectors a,b,c]
Resume (re-check after taking the listed operator actions):
Run: scripts/forge negotiate --mission <id> --resume
Known missions: windows_desktop_deployment, cinema_release_commit,
third_party_notification_workflow, capability_negotiation_selftest
(see capability_negotiation/missions.py to add more).

FORGE.RECONCILE
Read-only, staged, resumable reconciliation between the actual live
filesystem/git state at --root (default $HOME/forgeworld-runtime, NOT
$ROOT/$HOME/forgeworld) and every known candidate branch. Obeys RUNNING
SYSTEM > REPOSITORY ASSUMPTION > DOCUMENTATION: it never assumes a branch
is authoritative, it checks live content against every branch's tracked
blobs (via `git hash-object`, the same hash space `git ls-tree` reports --
NOT a plain sha256, which would never match). Ten stages (identity,
inventory, runtime_paths, untracked_modified, hash_artifacts, state_ledger,
reference_graph, branch_comparison, classify, finalize), each prints
STAGE N/10 [name]: PASS/FAIL and checkpoints immediately so a kill mid-run
loses at most the current stage. Classifies every artifact as
AUTHORITATIVE_LIVE / MATCHED_REPOSITORY / UNMERGED_LIVE / HISTORICAL /
GENERATED / UNKNOWN and writes a portable manifest.json + SUMMARY.md to
--out (default $HOME/forgeworld-reconcile-output, OUTSIDE --root so
running this never shows up in `git status` inside the repo). Makes ZERO
writes to --root -- no checkout, no merge, no reset, nothing mutating.
Run: scripts/forge reconcile
Re-run (skips stages already PASS): scripts/forge reconcile
Force full re-run: scripts/forge reconcile --force
Offline (skip branch comparison entirely): scripts/forge reconcile --no-fetch
