"""Lens v2 PRESENTATION: viewer-facing clarity over existing lens outputs.

This is not a new lens and not a re-run of any lens. It reads the seven
lens outputs, contradictions and unsupported claims an approved episode
candidate already cites, and sorts what they say for an audience:

  methodology_notes        how the analysis was made ("estimated from a word
                           list", "not inspected by this lens"). Production
                           notes; never shown as open questions to viewers.
  uncertainty_disclosures  what is genuinely not known about the subject.
  claims_requiring_disclosure
                           unsupported claims that ARE claims.
  audience_questions_asked unsupported "claims" that are really the audience
                           questions the cycle started from (a question
                           asserts nothing; it is shown as asked).
  contradiction_disclosures every contradiction, with a viewer phrasing and
                           an audience flag: VIEWER, or INTERNAL_ONLY for
                           production-process disagreements (e.g. "is this
                           ready to be an episode?"), which stay disclosed in
                           production notes but need not be broadcast.
  viewer_open_questions    questions designed for viewers: the audience's
                           own questions, viewer phrasings of VIEWER
                           contradictions, and the proposed experiment.

Classification is deterministic (fixed marker lists and a fixed question
table). The underlying records, labels and lists are never changed: every
item here also remains in the package's full disclosures.
"""
from __future__ import annotations

from cognition import cxp

PRESENTATION_VERSION = "2"
VIEWER = "VIEWER"
INTERNAL_ONLY = "INTERNAL_ONLY"

QUESTION_PRESENTATION = {
    cxp.Q_CLAIM_ESTABLISHED: ("Is this claim actually established by evidence yet?", VIEWER),
    cxp.Q_NEEDS_EXPERIMENT: ("Does this need a real test before anyone relies on it?", VIEWER),
    cxp.Q_READY_FOR_EPISODE: ("Production: is the material ready to become an episode?", INTERNAL_ONLY),
}

_METHODOLOGY_MARKERS = ("this lens", "word list", "commit message", "every scene must be checked",
                        "rule-based", "template")


def is_methodology_note(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _METHODOLOGY_MARKERS)


def present(candidate: dict, disagreements: list, audience_statements: list, experiments: list) -> dict:
    """candidate: the EPISODE_CANDIDATE payload; disagreements: the cycle
    artifact's preserved_disagreements cited by it; audience_statements: the
    text of the cited audience questions; experiments: the artifact's
    EXPERIMENT research candidates."""
    notes = [q for q in candidate["open_questions"] if is_methodology_note(q)]
    uncertainties = [q for q in candidate["open_questions"] if not is_methodology_note(q)]
    asked = [u for u in candidate["unsupported_claims"] if u in audience_statements]
    claims = [u for u in candidate["unsupported_claims"] if u not in audience_statements]

    contradictions = []
    for d in disagreements:
        phrasing, audience = QUESTION_PRESENTATION.get(d["question"], (d["question"].replace("_", " "), INTERNAL_ONLY))
        contradictions.append({"contradiction_id": d["contradiction_id"], "question": d["question"],
                               "viewer_phrasing": phrasing, "audience": audience, "positions": d["positions"]})

    viewer_questions = [{"question": q, "targets": "audience_question"} for q in audience_statements]
    viewer_questions += [{"question": c["viewer_phrasing"], "targets": c["contradiction_id"]}
                         for c in contradictions if c["audience"] == VIEWER]
    viewer_questions += [{"question": "What would you expect to happen if someone tried this: "
                                      f"{e['proposal'].rstrip('.')}?", "targets": e["candidate_id"]}
                         for e in experiments if e.get("proposal")]
    return {
        "presentation_version": PRESENTATION_VERSION,
        "methodology_notes": notes,
        "uncertainty_disclosures": uncertainties,
        "claims_requiring_disclosure": claims,
        "audience_questions_asked": asked,
        "contradiction_disclosures": contradictions,
        "viewer_open_questions": viewer_questions,
    }
