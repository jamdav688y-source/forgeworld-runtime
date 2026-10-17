"""FW-COGNITIVE-R3-001: the seven Maelstrom lenses -- deterministic,
rule-based interpreters of one shared, immutable LensBrief.

HONESTY BOUNDARY: these lenses are fixed vocabularies and templates. They
do not reason, they call no model, and their "independence" is only that
each reads the same brief and none sees another's output. Their value in
R3 is to exercise the contract (seven separately identified, provenance-
bearing interpretations whose disagreements are preserved) that model-backed
lenses can later be held to. Nothing a lens says is evidence: every lens
output is stored as UNVERIFIED_INTERPRETATION and can never be VERIFIED.

A lens returns a finding dict with exactly these keys:
    statement, positions, uncertainties, unsupported_claims, next_action,
    details
It cannot set its own evidence, verification, provenance or lineage --
the coordinator derives those labels and CXP enforces them.
Positions are on cxp.LENS_QUESTIONS, each SUPPORT / OPPOSE / UNCERTAIN.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType

from cognition import cxp

LENS_VERSION = "1"

_IMPLEMENTATION_SOURCE_TYPES = ("git_commit", "repository_file", "test_run")
_AUTHORITY_TERMS = ("authorize", "authorization", "grant", "grants", "permission", "receiver-held")
_SIGNIFICANCE_TERMS = ("authority", "authorize", "cannot", "consent", "control", "grant", "grants", "itself",
                       "permission", "receiver-held", "trust")
_INTERFACE_TERMS = ("execution", "fabric", "governed", "grant", "grants", "receiver-held", "request", "store")
_SPECIALIST_TERMS = ("authorization", "authorize", "capability", "execution", "fabric", "governed", "grant",
                     "grants", "provenance", "receiver-held")


@dataclass(frozen=True)
class LensBrief:
    """The one input every lens receives. Deeply immutable: mappings are
    MappingProxyType, sequences are tuples, so a lens that tries to edit
    it fails (and is isolated) instead of altering what the next lens sees."""

    brief_id: str
    topic: str
    inputs: tuple
    lineage: tuple
    open_contradictions: tuple
    facts: MappingProxyType

    def words(self) -> tuple:
        text = " ".join(i["statement"] for i in self.inputs).lower()
        return tuple(re.findall(r"[a-z][a-z-]*", text))

    def terms(self, vocabulary) -> list:
        return sorted(set(self.words()) & set(vocabulary))


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(v) for v in value)
    return value


def _finding(statement, positions=None, uncertainties=(), unsupported=(), next_action=None, details=None) -> dict:
    return {"statement": statement, "positions": dict(positions or {}), "uncertainties": list(uncertainties),
            "unsupported_claims": list(unsupported), "next_action": next_action, "details": dict(details or {})}


def _unverified_statements(brief: LensBrief) -> list:
    return sorted({i["statement"] for i in brief.inputs if i["verification"] != cxp.VER_VERIFIED})


class Muse:
    """M1 -- human significance, emotional resonance, curiosity."""
    lens_id, lens_version, representation = "MUSE", LENS_VERSION, cxp.REP_INFERENCE

    def analyze(self, brief: LensBrief) -> dict:
        found = brief.terms(_SIGNIFICANCE_TERMS)
        if not found:
            return _finding("No explicit human-significance markers appear in the input statements.",
                            {cxp.Q_READY_FOR_EPISODE: cxp.POS_UNCERTAIN},
                            ["significance is judged from a fixed word list, not from any audience"],
                            next_action="Identify a human stake before planning an episode.")
        stake = ("whether a system can grant itself permission"
                 if set(found) & set(_AUTHORITY_TERMS) else "who decides, and on what basis")
        return _finding(
            f"Human significance: {brief.topic} touches {', '.join(found)}; the human question is {stake}.",
            {cxp.Q_READY_FOR_EPISODE: cxp.POS_SUPPORT},
            ["emotional resonance is asserted from a fixed word list, not measured with any audience"],
            next_action=f"Frame the episode around the question of {stake}.",
            details={"significance_terms": found},
        )


class Scientist:
    """M2 -- hypotheses, causal reasoning, falsification."""
    lens_id, lens_version, representation = "SCIENTIST", LENS_VERSION, cxp.REP_HYPOTHESIS

    def analyze(self, brief: LensBrief) -> dict:
        verified = brief.facts["all_verified"]
        authority = bool(brief.terms(_AUTHORITY_TERMS))
        falsifier = ("a request that carries only requester-authored authority, with no receiver-held grant, "
                     "is executed" if authority else "the stated condition is removed and the outcome does not change")
        uncertainties = [] if "experiment" in brief.facts["source_types"] else ["no controlled experiment is referenced"]
        if not verified:
            uncertainties.append("no input is verified; the claim is so far a description, not a tested result")
        return _finding(
            f"Testable hypothesis: the observed claim would be refuted if {falsifier}.",
            {cxp.Q_CLAIM_ESTABLISHED: cxp.POS_SUPPORT if verified else cxp.POS_OPPOSE,
             cxp.Q_NEEDS_EXPERIMENT: cxp.POS_OPPOSE if verified else cxp.POS_SUPPORT},
            uncertainties, _unverified_statements(brief),
            next_action=("Run an adversarial test: present requester-authored authority with no receiver-held "
                         "grant and expect a refusal with zero execution." if authority
                         else "Define the observable that would refute the claim."),
            details={"falsifier": falsifier},
        )


class Architect:
    """M3 -- system dependencies, interfaces, capability composition."""
    lens_id, lens_version, representation = "ARCHITECT", LENS_VERSION, cxp.REP_INFERENCE

    def analyze(self, brief: LensBrief) -> dict:
        anchors = sorted({s["locator"] for t in brief.lineage for s in t["sources"]
                          if s["source_type"] in _IMPLEMENTATION_SOURCE_TYPES and s["locator"]})
        interfaces = brief.terms(_INTERFACE_TERMS)
        anchored = bool(anchors)
        return _finding(
            (f"Composition: the claim is anchored in {len(anchors)} implementation artifact(s) and names the "
             f"interfaces {', '.join(interfaces) or 'none'}." if anchored else
             "Composition: no implementation artifact anchors this claim."),
            {cxp.Q_CLAIM_ESTABLISHED: cxp.POS_SUPPORT if anchored else cxp.POS_UNCERTAIN},
            ["a commit message states intent; the code it changed was not inspected by this lens"],
            next_action="Map the change to the components it touches before an episode claims behaviour.",
            details={"implementation_anchors": anchors, "interface_terms": interfaces},
        )


class Challenger:
    """M4 -- contradictions, adversarial critique, failure modes."""
    lens_id, lens_version, representation = "CHALLENGER", LENS_VERSION, cxp.REP_INFERENCE

    def analyze(self, brief: LensBrief) -> dict:
        facts = brief.facts
        modes = []
        if facts["independent_origin_count"] < 2:
            modes.append("the claim rests on a single origin")
        if not facts["all_verified"]:
            modes.append("no input carries an admissible verification")
        if any(i["representation"] == cxp.REP_QUOTATION for i in brief.inputs) and "git_commit" in facts["source_types"]:
            modes.append("a quoted commit subject states intent, not observed behaviour")
        if brief.open_contradictions:
            modes.append(f"{len(brief.open_contradictions)} recorded contradiction(s) involve the inputs")
        weak = facts["independent_origin_count"] < 2 or not facts["all_verified"]
        return _finding(
            f"Adversarial review found {len(modes)} failure mode(s): " + ("; ".join(modes) if modes else "none") + ".",
            {cxp.Q_CLAIM_ESTABLISHED: cxp.POS_OPPOSE if weak else cxp.POS_UNCERTAIN,
             cxp.Q_READY_FOR_EPISODE: cxp.POS_OPPOSE if not facts["all_verified"] else cxp.POS_UNCERTAIN},
            modes, _unverified_statements(brief),
            next_action="Obtain an independent, admissible verification before any public claim.",
            details={"failure_modes": modes} if modes else {},
        )


class Storyweaver:
    """M5 -- narrative structure, episode concepts, cinematic communication."""
    lens_id, lens_version, representation = "STORYWEAVER", LENS_VERSION, cxp.REP_DRAMATIZATION

    def analyze(self, brief: LensBrief) -> dict:
        authority = bool(brief.terms(_AUTHORITY_TERMS))
        title = "We Built an AI That Cannot Give Itself Permission" if authority else f"Inside: {brief.topic}"
        unsupported = [] if brief.facts["all_verified"] else [
            "Act 3 shows a refusal on screen that the input does not itself demonstrate"]
        return _finding(
            f"Episode concept '{title}': a three-act structure built on {brief.topic}.",
            {cxp.Q_READY_FOR_EPISODE: cxp.POS_SUPPORT},
            ["dramatization: every scene must be checked against evidence before production"], unsupported,
            next_action="Draft a cold open for human review.",
            details={
                "working_title": title,
                "act_1": f"Setup: {brief.topic} -- what goes wrong when a system can authorize itself.",
                "act_2": "Confrontation: a request arrives carrying the authority it granted itself.",
                "act_3": "Resolution: the receiver holds the grant, and the self-granted request is refused.",
            },
        )


class Empath:
    """M6 -- audience interpretation, accessibility, comprehension."""
    lens_id, lens_version, representation = "EMPATH", LENS_VERSION, cxp.REP_INFERENCE

    def analyze(self, brief: LensBrief) -> dict:
        words = brief.words()
        specialist = [w for w in words if w in _SPECIALIST_TERMS]
        ratio_pct = (100 * len(specialist)) // max(len(words), 1)
        terms = sorted(set(specialist))
        return _finding(
            f"Comprehension: {len(specialist)} of {len(words)} words ({ratio_pct}%) are specialist terms; "
            + ("a general audience needs plain-language glosses." if terms else "the wording is accessible."),
            {cxp.Q_READY_FOR_EPISODE: cxp.POS_UNCERTAIN if ratio_pct >= 25 else cxp.POS_SUPPORT},
            ["audience comprehension is estimated from a word list, not tested with viewers"],
            next_action=("Write a one-sentence plain-language gloss for: " + ", ".join(terms) + ".") if terms else None,
            details={"specialist_terms": terms, "specialist_ratio_percent": str(ratio_pct)},
        )


class Catalyst:
    """M7 -- new hypotheses, candidate experiments, potential value."""
    lens_id, lens_version, representation = "CATALYST", LENS_VERSION, cxp.REP_HYPOTHESIS

    def analyze(self, brief: LensBrief) -> dict:
        authority = bool(brief.terms(_AUTHORITY_TERMS))
        experiment = ("Replay an expired and a revoked receiver-held grant against the receiver and record each "
                      "refusal as an experiment source." if authority
                      else "Design one observation that could distinguish the claim from its strongest alternative.")
        return _finding(
            f"Candidate experiment: {experiment}",
            {cxp.Q_NEEDS_EXPERIMENT: cxp.POS_SUPPORT},
            ["the value of this experiment is speculative until it runs"],
            next_action="Propose the experiment to the operator for authorization; do not run it from here.",
            details={"candidate_experiment": experiment,
                     "potential_value": "a recorded refusal could become admissible evidence for the episode"},
        )


LENSES = (Muse(), Scientist(), Architect(), Challenger(), Storyweaver(), Empath(), Catalyst())
