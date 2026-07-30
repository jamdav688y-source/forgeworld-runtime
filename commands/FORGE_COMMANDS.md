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
