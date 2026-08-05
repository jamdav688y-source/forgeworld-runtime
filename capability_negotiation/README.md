# Capability Negotiation Engine

Determines whether the current runtime can complete a mission *before*
execution begins, instead of discovering the gap mid-mission and
explaining it in prose after the fact.

## Why this exists

The Windows deployment mission for the Cinema Player was reported
blocked by manually calling a connector-listing tool and writing up the
reasoning by hand. This engine makes that check declarative,
re-runnable, and evidence-classified instead of something that has to be
re-derived every time the same question comes up.

## Files

- `states.py` -- the 6 capability states and 8 gap classifications.
- `missions.py` -- what each mission requires (specific capability ids,
  not vague tags). Add a mission here to gate it through this engine.
- `engine.py` -- `negotiate()`, `publish_report()`, `check_resume()`.
  Reuses `capabilities/discover.py`'s probes; never invents a capability.
- `negotiate.py` -- CLI (`python3 capability_negotiation/negotiate.py --mission <id>`).
- `test_engine.py` -- 14 tests, incl. proof that `policy_overrides` can
  only ever move a capability to BLOCKED_BY_POLICY, never force AVAILABLE.
- `reports/<mission_id>/` -- CAPABILITY_REGISTRY.json, CAPABILITY_REPORT.json,
  CAPABILITY_GAPS.json, OPERATOR_ACTIONS.md, CAPABILITY_EVIDENCE.json per
  mission, plus `reports/negotiation_history.jsonl` (append-only).

## Integration

- Registered in `capabilities/registry.json` as `capability_negotiation_engine`
  (self-check, always available -- it's part of this runtime).
- Exposed via `scripts/forge negotiate --mission <id>` and documented in
  `commands/FORGE_COMMANDS.md`.
- `router/mission_router.py route()` accepts an optional
  `--negotiate <mission_id>` flag: when given, negotiation runs first and
  routing is skipped entirely (`status: "queued_capability_gap"`) if the
  mission's requirements aren't met. Omit the flag and the router behaves
  exactly as before -- this is additive, not a breaking change.

## What "resume" actually means here

There is no background daemon watching for capability changes. "Resume"
means: re-invoke `check_resume()` (by hand, by a scheduled Routine, or by
an agent re-checking) and it will compare against the last published
report and flag anything newly satisfied as `DISCOVERED_AFTER_STARTUP`.
Stated plainly rather than implied to be more automatic than it is.

## Known limitation

`--live-connectors` evidence (for `connector`-type capabilities like
Slack/Gmail/remote desktop access) can only come from whatever is calling
this engine -- a plain Python process has no way to query a host's
connector session itself. Without it, connector-backed requirements
correctly resolve to `OPERATOR_REQUIRED`, not a guess in either direction.
