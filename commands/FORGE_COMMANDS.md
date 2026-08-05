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
