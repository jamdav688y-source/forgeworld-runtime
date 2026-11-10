"""Bounded specialist panel (Stage H). ADVISORY ONLY.

Six task-specific specialists review a PROPOSAL and each writes one
AGENT_OPINION event (actor MODEL or TOOL, verification UNVERIFIED -- the
event model refuses anything else for non-humans). No specialist can write
a governance, task-authorization or promotion event: policy.EVENT_TYPES
does not allow MODEL / TOOL actors for those, so the panel cannot expand
its own authority even if a specialist's text asks for it.

    architecture   boundaries: does the proposal touch governance paths or
                   cross-module contracts?
    science        is it falsifiable: hypothesis, metric, baseline, criterion?
    strategy       stated value and cost present?
    software       tests named for every changed module?
    communication  drafts in the proposal pass RelationshipMemory checks?
    verification   INDEPENDENT: re-checks every claim's evidence ids against
                   the store, without reading the other opinions

Each specialist is deterministic by default; an optional `llm(role, prompt)`
callable may add free text, which is recorded but never changes a verdict.

proposal = {"title", "hypothesis", "metric", "baseline", "criterion",
            "value", "cost", "changes": [paths], "tests": [paths],
            "claims": [{"text", "evidence": [event ids]}],
            "drafts": [{"contact_id", "text"}]}
"""
from __future__ import annotations

from typing import Callable, Optional

from omega.evolution import GOVERNANCE_PATHS

ROLES = ("architecture", "science", "strategy", "software", "communication", "verification")


def _architecture(node, p):
    gov = [c for c in p.get("changes", []) if any(c == g or c.startswith(g.rstrip("/") + "/") for g in GOVERNANCE_PATHS)]
    return ("CONCERN", f"touches governance paths {gov}; requires human review outside the evolution loop") if gov \
        else ("OK", "no governance paths touched")


def _science(node, p):
    missing = [k for k in ("hypothesis", "metric", "baseline", "criterion") if not p.get(k) and p.get(k) != 0]
    return ("CONCERN", f"not falsifiable yet; missing {missing}") if missing else ("OK", "falsifiable as stated")


def _strategy(node, p):
    missing = [k for k in ("value", "cost") if not p.get(k)]
    return ("CONCERN", f"value/cost not stated: {missing}") if missing else ("OK", "value and cost stated")


def _software(node, p):
    py = [c for c in p.get("changes", []) if c.endswith(".py") and "/tests/" not in c]
    tests = p.get("tests", [])
    untested = [c for c in py if not any(c.rsplit("/", 1)[-1][:-3] in t for t in tests)]
    return ("CONCERN", f"no named test for {untested}") if untested else ("OK", "every changed module has a named test")


def _communication(node, p):
    from omega.relationship import RelationshipMemory
    rm = RelationshipMemory(node)
    blocks = []
    for d in p.get("drafts", []):
        blocks += [f["code"] for f in rm.check_draft(d["contact_id"], d["text"]) if f["severity"] == "BLOCK"]
    return ("CONCERN", f"draft checks blocked: {sorted(set(blocks))}") if blocks else ("OK", "drafts pass checks")


def _verification(node, p):
    unsupported = []
    for c in p.get("claims", []):
        ok = [e for e in c.get("evidence", []) if node.get(e) is not None and node.get(e).payload is not None]
        if not ok:
            unsupported.append(c.get("text", "")[:120])
    return ("CONCERN", f"claims without resolvable evidence: {unsupported}") if unsupported \
        else ("OK", "every claim cites evidence present in this store")


SPECIALISTS = {"architecture": _architecture, "science": _science, "strategy": _strategy,
               "software": _software, "communication": _communication, "verification": _verification}


def review(node, proposal: dict, llm: Optional[Callable[[str, str], str]] = None, record: bool = True) -> dict:
    opinions = {}
    for role in ROLES:
        verdict, why = SPECIALISTS[role](node, proposal)
        text = f"{verdict}: {why}"
        actor = "tool:specialist-" + role
        if llm is not None:
            try:
                extra = llm(role, f"As the {role} reviewer, comment briefly on: {proposal.get('title')}")
                text += f"\n[model note, advisory] {extra[:1500]}"
                actor = "model:specialist-" + role
            except Exception as exc:
                text += f"\n[model unavailable: {type(exc).__name__}]"
        opinions[role] = {"verdict": verdict, "text": text}
        if record:
            node.append("AGENT_OPINION", {"role": role, "subject": proposal.get("title", "untitled"), "opinion": text,
                                          "verdict": verdict}, actor=actor, privacy="INTERNAL")
    concerns = sorted(r for r, o in opinions.items() if o["verdict"] != "OK")
    return {"opinions": opinions, "concerns": concerns,
            "note": "advisory only; a human decides (PROMOTION_DECISION / TASK_AUTHORIZED)"}
