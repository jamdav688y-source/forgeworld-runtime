"""FW-EPISODE-INTELLIGENCE-E1-001: episode candidates and human production
review.

EPISODE_CANDIDATE (derived CXP record) turns ONE completed, R4-governed
cognitive cycle into a reviewable YouTube episode draft. It is always
    representation DRAMATIZATION, evidence NONE, verification UNVERIFIED
and it derives from exactly the cycle's inputs, lens outputs and
contradictions, so lineage shows what it rests on and nothing it says can
outrank that. It is never lens input, never an R4 evidence root, never a
cycle source; anything derived from it counts as recycled cognition.

Its identity is its CXP record_id (content-addressed). A revision is a new
candidate that names the one it supersedes (revision n+1); a superseded
version can no longer be approved, and any revision needs its own review.

EPISODE_REVIEW (derived CXP record, HUMAN_ASSERTED) is one operator's
decision on one exact candidate version: APPROVED_FOR_PRODUCTION,
NEEDS_REVISION or REJECTED. Reviewers must be "operator-..." ids;
component ids cannot review.

PRODUCTION STATUS IS COMPUTED, NEVER TRUSTED. production_status()
re-validates every approval against the governor ledger and the immutable
cycle artifact, so an approval forged straight into the exchange counts for
nothing. An approval is valid only if:
    the candidate is the current (unsuperseded) revision;
    its cycle is COMPLETED in the R4 ledger and its artifact is intact and
      terminated COMPLETED with the full lens set (a partial cycle is
      incomplete);
    it cites that artifact's assembly, every lens output, EVERY preserved
      contradiction, every open question and every unsupported claim;
    no title or act uses verification language ("verified", "proven", ...)
      while the material is unverified;
    the reviewer explicitly accepted every OPEN contradiction and every
      unsupported claim it carries.
Acceptance records that a human chose to proceed with disclosed
uncertainty; it does not verify anything, and contradictions stay OPEN.
Status precedence is conservative: any REJECTED, then any NEEDS_REVISION,
then a valid approval. APPROVED_FOR_PRODUCTION authorizes preparing a
production package only: publication_authorized is always False.
"""
from __future__ import annotations

import re

from cognition import commerce, contradiction, cxp, cycle as cycle_module, lineage

DRAMATIZATION_LABEL = "DRAMATIZATION: not evidence; every scene must be checked against the cited records before production"
APPROVED = "APPROVED_FOR_PRODUCTION"
NEEDS_REVISION = "NEEDS_REVISION"
REJECTED = "REJECTED"
DECISIONS = (APPROVED, NEEDS_REVISION, REJECTED)
DRAFT = "DRAFT"
SUPERSEDED = "SUPERSEDED"

R_SUPERSEDED = "SUPERSEDED_REVISION"
R_CYCLE_INCOMPLETE = "CYCLE_INCOMPLETE"
R_ARTIFACT_INVALID = "ARTIFACT_MISSING_OR_ALTERED"
R_ASSEMBLY_MISMATCH = "ASSEMBLY_MISMATCH"
R_LENS_SET_MISMATCH = "LENS_SET_MISMATCH"
R_CONTRADICTION_OMITTED = "CONTRADICTION_OMITTED"
R_UNSUPPORTED_OMITTED = "UNSUPPORTED_CLAIM_OMITTED"
R_OPEN_QUESTION_OMITTED = "OPEN_QUESTION_OMITTED"
R_PRESENTED_AS_VERIFIED = "UNSUPPORTED_PRESENTED_AS_VERIFIED"
R_UNCERTAINTY_NOT_ACCEPTED = "UNCERTAINTY_NOT_ACCEPTED"

_CANDIDATE_KEYS = frozenset({"cycle_id", "cycle_artifact_id", "assembly_id", "lens_output_ids", "contradiction_ids",
                             "input_record_ids", "audience_question_ids", "working_title", "acts", "open_questions",
                             "unsupported_claims", "dramatization_label", "revision", "supersedes"})
_REVIEW_KEYS = frozenset({"candidate_id", "decision", "reviewer", "accepted_uncertainties", "notes"})
_CYCLE_ID = re.compile(r"^cxp-cycle-[0-9a-f]{64}$")
_ARTIFACT_ID = re.compile(r"^cxp-art-[0-9a-f]{64}$")
_ASSEMBLY_ID = re.compile(r"^cxp-asm-[0-9a-f]{64}$")
_RECORD_ID = re.compile(r"^cxp-rec-[0-9a-f]{64}$")
_REVIEWER = re.compile(r"^operator-[a-z0-9][a-z0-9-]{2,62}$")
_VERIFICATION_LANGUAGE = re.compile(r"\b(verified|proven|proved|confirmed|guaranteed|scientifically shown|fact)\b",
                                    re.IGNORECASE)
_INPUT_KINDS = (cxp.KIND_OBSERVATION, cxp.KIND_CLAIM, cxp.KIND_AUDIENCE_QUESTION)
MAX_ACTS = 12


class EpisodeError(Exception):
    def __init__(self, reasons):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)


def _refuse(code, detail):
    raise cxp.CXPError(code, detail)


def _ids(value, pattern, what, minimum=0, maximum=64):
    if (not isinstance(value, list) or not minimum <= len(value) <= maximum or value != sorted(set(value))
            or not all(isinstance(v, str) and pattern.match(v) for v in value)):
        _refuse(cxp.E_MALFORMED, f"{what} must be a sorted, duplicate-free list of {minimum}-{maximum} ids")


def _texts(value, what, maximum=32):
    if (not isinstance(value, list) or len(value) > maximum
            or not all(isinstance(v, str) and v.strip() and len(v) <= cxp.MAX_STATEMENT_CHARS for v in value)):
        _refuse(cxp.E_MALFORMED, f"{what} must be a list of non-empty strings")


# ---------------------------------------------------------------------------
# schemas (called by cxp)
# ---------------------------------------------------------------------------

def check_candidate_payload(payload: dict) -> None:
    if set(payload) != _CANDIDATE_KEYS:
        _refuse(cxp.E_MALFORMED, f"EPISODE_CANDIDATE payload requires exactly {sorted(_CANDIDATE_KEYS)}")
    for name, pattern in (("cycle_id", _CYCLE_ID), ("cycle_artifact_id", _ARTIFACT_ID), ("assembly_id", _ASSEMBLY_ID)):
        if not isinstance(payload[name], str) or not pattern.match(payload[name]):
            _refuse(cxp.E_MALFORMED, f"{name} is missing or malformed")
    _ids(payload["lens_output_ids"], _RECORD_ID, "lens_output_ids", 1, len(cxp.LENS_IDS))
    _ids(payload["contradiction_ids"], _RECORD_ID, "contradiction_ids", 0, len(cxp.LENS_QUESTIONS))
    _ids(payload["input_record_ids"], _RECORD_ID, "input_record_ids", 1, 8)
    _ids(payload["audience_question_ids"], _RECORD_ID, "audience_question_ids", 0, 8)
    if not set(payload["audience_question_ids"]) <= set(payload["input_record_ids"]):
        _refuse(cxp.E_MALFORMED, "audience_question_ids must be among input_record_ids")
    title = payload["working_title"]
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        _refuse(cxp.E_MALFORMED, "working_title must be a non-empty string")
    acts = payload["acts"]
    if (not isinstance(acts, list) or not 1 <= len(acts) <= MAX_ACTS
            or not all(isinstance(a, dict) and set(a) == {"label", "text"} and isinstance(a["label"], str)
                       and a["label"].strip() and isinstance(a["text"], str) and a["text"].strip() for a in acts)):
        _refuse(cxp.E_MALFORMED, f"acts must be 1-{MAX_ACTS} objects of exactly {{label, text}}")
    _texts(payload["open_questions"], "open_questions")
    _texts(payload["unsupported_claims"], "unsupported_claims")
    if payload["dramatization_label"] != DRAMATIZATION_LABEL:
        _refuse(cxp.E_MALFORMED, "dramatization_label must be the fixed disclosure")
    revision, supersedes = payload["revision"], payload["supersedes"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        _refuse(cxp.E_MALFORMED, "revision must be a positive integer")
    if (revision == 1) != (supersedes is None) or (supersedes is not None and not _RECORD_ID.match(str(supersedes))):
        _refuse(cxp.E_MALFORMED, "revision 1 supersedes nothing; every later revision names the candidate it replaces")


def check_candidate_labels(payload, provenance, representation, evidence, verification, derived_from) -> None:
    if (representation, evidence, verification) != (cxp.REP_DRAMATIZATION, cxp.EV_NONE, cxp.VER_UNVERIFIED):
        _refuse(cxp.E_KIND_RULE, "an EPISODE_CANDIDATE is always DRAMATIZATION, evidence NONE, UNVERIFIED")
    if provenance not in (cxp.UNVERIFIED_INTERPRETATION, cxp.HUMAN_ASSERTED):
        _refuse(cxp.E_KIND_RULE, "EPISODE_CANDIDATE provenance must be UNVERIFIED_INTERPRETATION or HUMAN_ASSERTED")
    expected = sorted(set(payload["lens_output_ids"]) | set(payload["contradiction_ids"]) | set(payload["input_record_ids"]))
    if list(derived_from) != expected:
        _refuse(cxp.E_KIND_RULE, "EPISODE_CANDIDATE must derive from exactly its inputs, lens outputs and contradictions")


def check_review_payload(payload: dict) -> None:
    if set(payload) != _REVIEW_KEYS:
        _refuse(cxp.E_MALFORMED, f"EPISODE_REVIEW payload requires exactly {sorted(_REVIEW_KEYS)}")
    if not isinstance(payload["candidate_id"], str) or not _RECORD_ID.match(payload["candidate_id"]):
        _refuse(cxp.E_MALFORMED, "candidate_id must be a record id")
    if payload["decision"] not in DECISIONS:
        _refuse(cxp.E_MALFORMED, f"decision must be one of {DECISIONS}")
    if not isinstance(payload["reviewer"], str) or not _REVIEWER.match(payload["reviewer"]):
        _refuse(cxp.E_MALFORMED, "reviewer must be a human operator id (operator-<slug>)")
    _texts(payload["accepted_uncertainties"], "accepted_uncertainties", maximum=64)
    if payload["notes"] is not None:
        commerce._check_summary(payload["notes"])


def check_review_labels(payload, provenance, representation, evidence, verification, derived_from) -> None:
    if provenance != cxp.HUMAN_ASSERTED:
        _refuse(cxp.E_KIND_RULE, "an EPISODE_REVIEW is a human decision: provenance must be HUMAN_ASSERTED")
    if (representation, evidence, verification) != (cxp.REP_PARAPHRASE, cxp.EV_NONE, cxp.VER_UNVERIFIED):
        _refuse(cxp.E_KIND_RULE, "an EPISODE_REVIEW is PARAPHRASE, evidence NONE, UNVERIFIED: it decides, it does not verify")
    if list(derived_from) != [payload["candidate_id"]]:
        _refuse(cxp.E_KIND_RULE, "an EPISODE_REVIEW derives from exactly the candidate it reviews")


def candidate_metadata(payload: dict) -> dict:
    return {k: payload[k] for k in ("cycle_id", "cycle_artifact_id", "revision", "supersedes")}


def review_metadata(payload: dict) -> dict:
    return {k: payload[k] for k in ("candidate_id", "decision", "reviewer")}


def check_transition(kind: str, payload: dict, records: dict, lookup) -> None:
    """Structural lineage checks at ingest (called by the exchange under its
    lock): every reference resolves to the right kind of record, the lens
    outputs really are this cycle's analysis of these inputs, the
    contradictions are between those lens outputs, and revisions form one
    chain per cycle."""
    if kind == cxp.KIND_EPISODE_REVIEW:
        target = lookup(payload["candidate_id"])
        if target is None or target["kind"] != cxp.KIND_EPISODE_CANDIDATE:
            _refuse(cxp.E_TRANSITION_REFUSED, "a review must target an accepted EPISODE_CANDIDATE")
        return
    inputs = payload["input_record_ids"]
    for rid in inputs:
        meta = lookup(rid)
        if meta is None or meta["kind"] not in _INPUT_KINDS:
            _refuse(cxp.E_TRANSITION_REFUSED, f"input {rid} is not an accepted observation, claim or audience question")
    for rid in payload["audience_question_ids"]:
        if lookup(rid)["kind"] != cxp.KIND_AUDIENCE_QUESTION:
            _refuse(cxp.E_TRANSITION_REFUSED, f"{rid} is not an audience question")
    if sorted(r for r in inputs if lookup(r)["kind"] == cxp.KIND_AUDIENCE_QUESTION) != payload["audience_question_ids"]:
        _refuse(cxp.E_TRANSITION_REFUSED, "every audience question among the inputs must be cited as motivating")
    for rid in payload["lens_output_ids"]:
        meta = lookup(rid)
        if meta is None or meta["kind"] != cxp.KIND_LENS_OUTPUT or meta["derived_from"] != inputs:
            _refuse(cxp.E_TRANSITION_REFUSED, f"{rid} is not a lens output over exactly these inputs")
    for rid in payload["contradiction_ids"]:
        meta = lookup(rid)
        if meta is None or meta["kind"] != cxp.KIND_CONTRADICTION or not set(meta["contradiction_claims"]) <= set(payload["lens_output_ids"]):
            _refuse(cxp.E_TRANSITION_REFUSED, f"{rid} is not a contradiction between the cited lens outputs")
    previous = payload["supersedes"]
    if previous is not None:
        prior = lookup(previous)
        if (prior is None or prior["kind"] != cxp.KIND_EPISODE_CANDIDATE or prior["erased"]
                or prior["episode"]["cycle_id"] != payload["cycle_id"]
                or prior["episode"]["revision"] + 1 != payload["revision"]):
            _refuse(cxp.E_TRANSITION_REFUSED, "a revision must supersede the previous revision of the same cycle's candidate")
        if any(m.get("episode", {}).get("supersedes") == previous for m in records.values()):
            _refuse(cxp.E_TRANSITION_REFUSED, "that revision has already been superseded")


# ---------------------------------------------------------------------------
# studio
# ---------------------------------------------------------------------------

class EpisodeStudio:
    """Drafts candidates from completed cycle artifacts and records human
    reviews. It can prepare nothing for publication by itself."""

    def __init__(self, runner):
        self.runner = runner
        self.exchange = runner.exchange
        self.governor = runner.governor

    @property
    def grants_execution_authority(self) -> bool:
        return False

    # -- drafting -------------------------------------------------------------------

    def _artifact(self, artifact_id: str) -> dict:
        try:
            return self.runner.load(artifact_id)
        except (OSError, ValueError, cycle_module.CycleArtifactError):
            raise EpisodeError([R_ARTIFACT_INVALID]) from None

    def _cycle_completed(self, cycle_id: str) -> bool:
        return any(e["entry"] == "COMPLETED" and e["cycle_id"] == cycle_id for e in self.governor.ledger_entries())

    @staticmethod
    def _references(artifact: dict) -> dict:
        assembly = artifact["assembly"]
        inputs = sorted(c["record_id"] for c in artifact["evidence_classification"])
        return {
            "cycle_id": artifact["governor_decision"]["cycle_id"],
            "cycle_artifact_id": artifact["artifact_id"],
            "assembly_id": assembly["assembly_id"],
            "lens_output_ids": sorted(r["record_id"] for r in assembly["lens_results"] if r["available"]),
            "contradiction_ids": sorted(d["contradiction_id"] for d in artifact["preserved_disagreements"]
                                        if d["contradiction_id"]),
            "input_record_ids": inputs,
            "audience_question_ids": sorted(c["record_id"] for c in artifact["evidence_classification"]
                                            if c["kind"] == cxp.KIND_AUDIENCE_QUESTION),
            "open_questions": sorted(assembly["open_questions"]),
            "unsupported_claims": sorted(assembly["unsupported_claims"]),
        }

    def _event(self, payload: dict, observed_at: str, provenance: str) -> dict:
        parents = sorted(set(payload["lens_output_ids"]) | set(payload["contradiction_ids"]) | set(payload["input_record_ids"]))
        privacy = cxp.PRIVACY_CLASSES[max(cxp.PRIVACY_CLASSES.index(self.exchange.record_metadata(p)["privacy"])
                                          for p in parents)]
        return {"schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_EPISODE_CANDIDATE,
                "representation": cxp.REP_DRAMATIZATION, "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
                "provenance": provenance, "privacy": privacy, "payload": payload, "sources": [],
                "derived_from": parents, "verification_ref": None, "consent_ref": None,
                "occurrence": {"emitter_id": "episode-studio", "observed_at": observed_at,
                               "correlation_id": payload["cycle_id"], "causation_id": None}}

    def _ingest(self, event: dict) -> str:
        receipt = self.exchange.ingest(event)
        if receipt.status == "REJECTED":
            raise EpisodeError([f"{receipt.error_code}: {receipt.detail}"])
        return receipt.record_id

    def draft(self, artifact_id: str, observed_at: str) -> str:
        """Revision 1 of a candidate, built only from a completed cycle's
        immutable artifact. Nothing missing is invented: without a
        STORYWEAVER seed there is no title and no draft."""
        artifact = self._artifact(artifact_id)
        if artifact["termination"] not in (cycle_module.COMPLETED_WITH_CANDIDATES, cycle_module.COMPLETED_NO_CANDIDATES) \
                or not self._cycle_completed(artifact["governor_decision"]["cycle_id"]):
            raise EpisodeError([R_CYCLE_INCOMPLETE])
        seed = artifact["assembly"].get("episode_planning_seed")
        if not seed or not seed.get("working_title"):
            raise EpisodeError(["MISSING_STORY_SEED"])
        acts = [{"label": key, "text": seed[key]} for key in sorted(seed) if key.startswith("act_")]
        payload = {**self._references(artifact), "working_title": seed["working_title"], "acts": acts,
                   "dramatization_label": DRAMATIZATION_LABEL, "revision": 1, "supersedes": None}
        return self._ingest(self._event(payload, observed_at, cxp.UNVERIFIED_INTERPRETATION))

    def revise(self, candidate_id: str, observed_at: str, working_title: str = None, acts=None) -> str:
        """A human edit: a NEW candidate (revision n+1) superseding this one.
        References are re-derived from the artifact, never carried over by
        hand, so a revision cannot drop a contradiction."""
        current = self.exchange.get_record(candidate_id)
        if current is None or current.kind != cxp.KIND_EPISODE_CANDIDATE:
            raise EpisodeError(["NOT_A_CANDIDATE"])
        old = current.payload()
        payload = {**self._references(self._artifact(old["cycle_artifact_id"])),
                   "working_title": working_title or old["working_title"], "acts": acts or old["acts"],
                   "dramatization_label": DRAMATIZATION_LABEL, "revision": old["revision"] + 1,
                   "supersedes": candidate_id}
        return self._ingest(self._event(payload, observed_at, cxp.HUMAN_ASSERTED))

    # -- review -----------------------------------------------------------------------

    def _superseded(self, candidate_id: str) -> bool:
        return any(m.get("episode", {}).get("supersedes") == candidate_id and not m["erased"]
                   for m in self.exchange.all_record_metadata())

    def approval_problems(self, candidate_id: str, accepted_uncertainties=()) -> list:
        """Everything that would make an approval of this exact version invalid."""
        record = self.exchange.get_record(candidate_id)
        if record is None or record.kind != cxp.KIND_EPISODE_CANDIDATE:
            return ["NOT_A_CANDIDATE"]
        c = record.payload()
        problems = []
        if self._superseded(candidate_id):
            problems.append(R_SUPERSEDED)
        try:
            artifact = self._artifact(c["cycle_artifact_id"])
        except EpisodeError as exc:
            return problems + exc.reasons
        if (artifact["termination"] != cycle_module.COMPLETED_WITH_CANDIDATES
                and artifact["termination"] != cycle_module.COMPLETED_NO_CANDIDATES) or not self._cycle_completed(c["cycle_id"]):
            problems.append(R_CYCLE_INCOMPLETE)
        refs = self._references(artifact)
        if (refs["cycle_id"], refs["assembly_id"], refs["input_record_ids"]) != (c["cycle_id"], c["assembly_id"], c["input_record_ids"]):
            problems.append(R_ASSEMBLY_MISMATCH)
        if refs["lens_output_ids"] != c["lens_output_ids"]:
            problems.append(R_LENS_SET_MISMATCH)
        if not set(refs["contradiction_ids"]) <= set(c["contradiction_ids"]):
            problems.append(R_CONTRADICTION_OMITTED)
        if not set(refs["unsupported_claims"]) <= set(c["unsupported_claims"]):
            problems.append(R_UNSUPPORTED_OMITTED)
        if not set(refs["open_questions"]) <= set(c["open_questions"]):
            problems.append(R_OPEN_QUESTION_OMITTED)
        texts = [c["working_title"]] + [a["text"] for a in c["acts"]]
        unverified = any(self.exchange.record_metadata(r)["verification"] != cxp.VER_VERIFIED for r in c["input_record_ids"])
        if (c["unsupported_claims"] or unverified) and any(_VERIFICATION_LANGUAGE.search(t) for t in texts):
            problems.append(R_PRESENTED_AS_VERIFIED)
        open_contradictions = [cid for cid in c["contradiction_ids"]
                               if contradiction.assess(self.exchange, cid)["status"] == contradiction.OPEN]
        if not set(open_contradictions) | set(c["unsupported_claims"]) <= set(accepted_uncertainties):
            problems.append(R_UNCERTAINTY_NOT_ACCEPTED)
        return problems

    def review(self, candidate_id: str, decision: str, reviewer: str, observed_at: str,
               accepted_uncertainties=(), notes: str = None) -> str:
        """Record one human decision on one exact candidate version. An
        approval that would not be valid is refused, not recorded."""
        if self.governor._active_cycles:
            raise EpisodeError(["REVIEW_DURING_RUNNING_CYCLE"])
        candidate = self.exchange.record_metadata(candidate_id)
        if candidate is None or candidate["kind"] != cxp.KIND_EPISODE_CANDIDATE:
            raise EpisodeError(["NOT_A_CANDIDATE"])
        if reviewer is None or not _REVIEWER.match(str(reviewer)):
            raise EpisodeError(["REVIEWER_NOT_A_HUMAN_OPERATOR"])
        if decision == APPROVED:
            problems = self.approval_problems(candidate_id, accepted_uncertainties)
            if problems:
                raise EpisodeError(problems)
        payload = {"candidate_id": candidate_id, "decision": decision, "reviewer": reviewer,
                   "accepted_uncertainties": sorted(set(accepted_uncertainties)), "notes": notes}
        event = {"schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_EPISODE_REVIEW,
                 "representation": cxp.REP_PARAPHRASE, "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
                 "provenance": cxp.HUMAN_ASSERTED,
                 "privacy": candidate["privacy"],
                 "payload": payload, "sources": [], "derived_from": [candidate_id], "verification_ref": None,
                 "consent_ref": None,
                 "occurrence": {"emitter_id": reviewer, "observed_at": observed_at, "correlation_id": None,
                                "causation_id": None}}
        return self._ingest(event)

    def production_status(self, candidate_id: str) -> dict:
        reviews = []
        for meta in self.exchange.all_record_metadata():
            r = meta.get("episode_review")
            if r and r["candidate_id"] == candidate_id and not meta["erased"]:
                accepted = self.exchange.get_record(meta["record_id"]).payload()["accepted_uncertainties"]
                problems = self.approval_problems(candidate_id, accepted) if r["decision"] == APPROVED else []
                reviews.append({"review_id": meta["record_id"], "decision": r["decision"], "reviewer": r["reviewer"],
                                "valid": not problems, "problems": problems})
        decisions = {r["decision"] for r in reviews}
        if self._superseded(candidate_id):
            status = SUPERSEDED
        elif REJECTED in decisions:
            status = REJECTED
        elif NEEDS_REVISION in decisions:
            status = NEEDS_REVISION
        elif any(r["decision"] == APPROVED and r["valid"] for r in reviews):
            status = APPROVED
        else:
            status = DRAFT
        return {"candidate_id": candidate_id, "status": status, "reviews": reviews,
                "production_preparation_authorized": status == APPROVED,
                "publication_authorized": False, "grants_execution_authority": False}

    def audit(self, candidate_id: str) -> dict:
        """Contradiction and provenance audit of one candidate version."""
        record = self.exchange.get_record(candidate_id)
        c = record.payload()
        trace = lineage.trace(self.exchange.record_metadata, candidate_id)
        return {
            "candidate_id": candidate_id,
            "labels": {"representation": record.representation, "evidence": record.evidence,
                       "verification": record.verification, "provenance": record.provenance},
            "epistemic_class": trace["epistemic_class"],
            "observation_roots": trace["observation_roots"],
            "sources": [{k: s[k] for k in ("source_type", "locator", "independence_basis")} for s in trace["sources"]],
            "contradictions": [{"contradiction_id": cid, "status": contradiction.assess(self.exchange, cid)["status"]}
                               for cid in c["contradiction_ids"]],
            "unsupported_claims": c["unsupported_claims"],
            "open_questions": c["open_questions"],
            "approval_problems_without_acceptance": self.approval_problems(candidate_id),
        }
