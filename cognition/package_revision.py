"""FW-PRODUCTION-E3-001: governed producer editing of production packages.

A human producer edits a package through a fixed set of structured
operations. Every edit is CLASSIFIED before anything is written:

    PRESENTATION  changes how material is shown, not what it claims; may
                  proceed through this workflow.
    CLAIM_CHANGE  would change, strengthen or un-hedge what the episode
                  asserts; refused here and returned to the episode-
                  candidate revision and human-review process (E1).
    AMBIGUOUS     cannot be classified safely; refused (fail closed).

One non-PRESENTATION edit refuses the whole revision. Classification is
deterministic: fixed operation table, fixed editable fields per scene
label, and fixed word patterns (verification language that is not negated,
absolutes that were not already there, hedges that disappear, framing a
dramatization as real events, quotations altered, lens statements reworded,
hypotheses restated without a hypothesis marker).

Operations and what they may touch:
    set_scene_text     title / on_screen_text / narration_guidance / transition
    set_narration      narration lines (DRAMATIZATION, HYPOTHESIS scenes;
                       QUOTED_SOURCE quotations are CLAIM_CHANGE;
                       INTERPRETATION lens statements are AMBIGUOUS)
    set_visual_prompts visual-generation prompts (dramatizations keep their
                       DRAMATIZATION label)
    set_audio          music / pacing
    reorder_scenes     a permutation of the current scene ids
    remove_scene       INTERNAL_ONLY scenes only
    set_viewer_questions  future intake questions (must be questions)
    set_package_text   episode_title, youtube_description_draft (must keep
                       the dramatization disclosure), pinned_comment_draft,
                       thumbnail_concepts, opening_hook_concepts
Labels, source refs, citations, disclosures, lineage, the citation sheet,
experiment references, presentation, governance and the publication flags
have no operation at all.

A revision is a NEW content-addressed package (never an overwrite) whose
revision block names its predecessor, the human editor ("operator-..."),
and every classified change; its CXP record derives from the predecessor.
Only the latest version can be revised (one chain). Before writing, the
predecessor is re-loaded (tamper check), the underlying candidate approval
is re-validated, the new package passes validate_package(), and a
preservation check confirms nothing outside the allowed fields changed.

PACKAGE_REVIEW records one human decision on one exact package_id. Because
package ids are content addresses, any revision produces a new id: the
predecessor becomes SUPERSEDED and its approval no longer counts, so
changed content always needs a fresh review. Approval locks the version for
production preparation; publication_authorized stays False.
"""
from __future__ import annotations

import copy
import re

from cognition import cxp, episode as ep, presentation, production as pr

PRESENTATION_CHANGE = "PRESENTATION"
CLAIM_CHANGE = "CLAIM_CHANGE"
AMBIGUOUS = "AMBIGUOUS"
SUPERSEDED = "SUPERSEDED"
DRAFT = "DRAFT"

_HEDGES = re.compile(r"\b(may|might|could|possibly|perhaps|would|unverified|uncertain|unresolved|open|unknown|unclear|"
                     r"not yet|hypothes\w*|dramati[sz]\w*|reconstruction|illustrative|propos\w*|suggest\w*|if|test\w*)\b|\?",
                     re.IGNORECASE)
_HYPOTHESIS_MARKERS = re.compile(r"\b(may|might|could|would|if|propos\w*|test\w*|hypothes\w*|not yet|unknown|"
                                 r"unverified|uncertain|open|we could|try|tried)\b|\?", re.IGNORECASE)
_ABSOLUTES = re.compile(r"\b(always|never|definitely|certainly|undeniabl\w*|unquestionabl\w*|clearly|proves?|proved|"
                        r"shows that|demonstrates?|established|the truth|beyond doubt|guaranteed)\b", re.IGNORECASE)
_FACT_FRAMING = re.compile(r"\b(real|actual) (footage|events?|recordings?)\b|\bthis (really )?happened\b|\btrue story\b|"
                           r"\bnot a (dramati[sz]ation|reconstruction)\b|\bdocumentary footage\b", re.IGNORECASE)
_SCENE_TEXT_FIELDS = ("title", "on_screen_text", "narration_guidance", "transition")
_PACKAGE_TEXT_FIELDS = ("episode_title", "youtube_description_draft", "pinned_comment_draft")
_PACKAGE_LIST_FIELDS = ("thumbnail_concepts", "opening_hook_concepts")
_REVIEW_KEYS = frozenset({"package_record_id", "package_id", "decision", "reviewer", "notes"})


class RevisionRefused(Exception):
    def __init__(self, reasons, classifications=()):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)
        self.classifications = list(classifications)


# ---------------------------------------------------------------------------
# PACKAGE_REVIEW record rules (called by cxp / exchange)
# ---------------------------------------------------------------------------

def check_review_payload(payload: dict) -> None:
    if set(payload) != _REVIEW_KEYS:
        raise cxp.CXPError(cxp.E_MALFORMED, f"PACKAGE_REVIEW payload requires exactly {sorted(_REVIEW_KEYS)}")
    if payload["decision"] not in ep.DECISIONS:
        raise cxp.CXPError(cxp.E_MALFORMED, f"decision must be one of {ep.DECISIONS}")
    if not isinstance(payload["reviewer"], str) or not ep._REVIEWER.match(payload["reviewer"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "reviewer must be a human operator id (operator-<slug>)")
    if not isinstance(payload["package_id"], str) or not pr._PACKAGE_ID.match(payload["package_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "package_id is malformed")
    if payload["notes"] is not None:
        from cognition import commerce
        commerce._check_summary(payload["notes"])


def check_review_labels(payload, provenance, representation, evidence, verification, derived_from) -> None:
    if (provenance, representation, evidence, verification) != (
            cxp.HUMAN_ASSERTED, cxp.REP_PARAPHRASE, cxp.EV_NONE, cxp.VER_UNVERIFIED):
        raise cxp.CXPError(cxp.E_KIND_RULE, "a PACKAGE_REVIEW is a human decision: HUMAN_ASSERTED, PARAPHRASE, NONE, UNVERIFIED")
    if list(derived_from) != [payload["package_record_id"]]:
        raise cxp.CXPError(cxp.E_KIND_RULE, "a PACKAGE_REVIEW derives from exactly the package record it reviews")


def check_review_transition(payload: dict, lookup) -> None:
    target = lookup(payload["package_record_id"])
    if (target is None or target["kind"] != cxp.KIND_PRODUCTION_PACKAGE
            or target["production_package"]["package_id"] != payload["package_id"]):
        raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "a package review must target that exact PRODUCTION_PACKAGE version")


# ---------------------------------------------------------------------------
# classification
# ---------------------------------------------------------------------------

def _text_problem(old: str, new: str):
    if not isinstance(new, str) or not new.strip():
        return AMBIGUOUS, "EMPTY_OR_NON_TEXT"
    if pr.asserts_verification(new):
        return CLAIM_CHANGE, "VERIFICATION_LANGUAGE"
    if _FACT_FRAMING.search(new):
        return CLAIM_CHANGE, "DRAMATIZATION_PRESENTED_AS_FACT"
    if _ABSOLUTES.search(new) and not _ABSOLUTES.search(old or ""):
        return CLAIM_CHANGE, "CERTAINTY_STRENGTHENED"
    if _HEDGES.search(old or "") and not _HEDGES.search(new):
        return CLAIM_CHANGE, "UNCERTAINTY_REMOVED"
    return None


def classify(package: dict, edit: dict) -> dict:
    """Deterministic classification of one structured edit."""
    def result(cls, reason, summary=""):
        return {"op": edit.get("op") if isinstance(edit, dict) else None, "class": cls, "reason": reason,
                "summary": summary}

    if not isinstance(edit, dict) or not isinstance(edit.get("op"), str):
        return result(AMBIGUOUS, "UNRECOGNISED_EDIT")
    scenes = {s["scene_id"]: s for s in package["scenes"]}
    op = edit["op"]
    scene = scenes.get(edit.get("scene_id")) if "scene_id" in edit else None
    if "scene_id" in edit and scene is None:
        return result(AMBIGUOUS, "UNKNOWN_SCENE")
    allowed_keys = {"set_scene_text": {"op", "scene_id", "field", "value"}, "set_narration": {"op", "scene_id", "lines"},
                    "set_visual_prompts": {"op", "scene_id", "prompts"}, "set_audio": {"op", "scene_id", "music", "pacing"},
                    "reorder_scenes": {"op", "scene_ids"}, "remove_scene": {"op", "scene_id"},
                    "set_viewer_questions": {"op", "questions"}, "set_package_text": {"op", "field", "value"}}
    if op not in allowed_keys or set(edit) != allowed_keys[op]:
        return result(AMBIGUOUS, "UNRECOGNISED_EDIT")

    if op == "set_scene_text":
        if edit["field"] not in _SCENE_TEXT_FIELDS:
            return result(AMBIGUOUS, "FIELD_NOT_EDITABLE")
        problem = _text_problem(scene[edit["field"]], edit["value"])
        return result(*problem) if problem else result(PRESENTATION_CHANGE, "WORDING", f"{scene['scene_id']}.{edit['field']}")

    if op == "set_narration":
        lines = edit["lines"]
        if not isinstance(lines, list) or not lines or not all(isinstance(l, str) and l.strip() for l in lines):
            return result(AMBIGUOUS, "EMPTY_OR_NON_TEXT")
        if lines == scene["narration_lines"]:
            return result(PRESENTATION_CHANGE, "NO_CHANGE", scene["scene_id"])
        if scene["label"] == pr.QUOTED_SOURCE:
            return result(CLAIM_CHANGE, "QUOTATION_ALTERED")
        if scene["label"] == pr.INTERPRETATION:
            return result(AMBIGUOUS, "LENS_STATEMENT_REWORDING")
        problem = _text_problem(" ".join(scene["narration_lines"]), " ".join(lines))
        if scene["label"] == pr.HYPOTHESIS and (problem is None or problem[1] == "UNCERTAINTY_REMOVED"):
            for line in lines:  # the more specific reason wins over a generic removed hedge
                if line not in scene["narration_lines"] and not _HYPOTHESIS_MARKERS.search(line):
                    return result(CLAIM_CHANGE, "HYPOTHESIS_STATED_AS_RESULT")
        if problem:
            return result(*problem)
        return result(PRESENTATION_CHANGE, "SCRIPT_PHRASING", scene["scene_id"])

    if op == "set_visual_prompts":
        prompts = edit["prompts"]
        if not isinstance(prompts, list) or not prompts or not all(isinstance(p, str) and p.strip() for p in prompts):
            return result(AMBIGUOUS, "EMPTY_OR_NON_TEXT")
        for p in prompts:
            if pr.asserts_verification(p) or _FACT_FRAMING.search(p):
                return result(CLAIM_CHANGE, "DRAMATIZATION_PRESENTED_AS_FACT")
            if scene["label"] == pr.DRAMATIZATION and "DRAMATIZATION" not in p:
                return result(CLAIM_CHANGE, "DRAMATIZATION_LABEL_REMOVED")
        return result(PRESENTATION_CHANGE, "VISUAL_PROMPTS", scene["scene_id"])

    if op == "set_audio":
        for value in (edit["music"], edit["pacing"]):
            if not isinstance(value, str) or not value.strip():
                return result(AMBIGUOUS, "EMPTY_OR_NON_TEXT")
            if pr.asserts_verification(value):
                return result(CLAIM_CHANGE, "VERIFICATION_LANGUAGE")
        return result(PRESENTATION_CHANGE, "AUDIO_PACING", scene["scene_id"])

    if op == "reorder_scenes":
        if not isinstance(edit["scene_ids"], list) or sorted(edit["scene_ids"]) != sorted(scenes):
            return result(AMBIGUOUS, "NOT_A_PERMUTATION")
        return result(PRESENTATION_CHANGE, "SCENE_ORDER", " > ".join(i.split("-")[1] for i in edit["scene_ids"]))

    if op == "remove_scene":
        if scene["audience"] != presentation.INTERNAL_ONLY:
            return result(CLAIM_CHANGE, "REMOVES_VIEWER_FACING_SCENE")
        return result(PRESENTATION_CHANGE, "INTERNAL_SCENE_REMOVED", scene["scene_id"])

    if op == "set_viewer_questions":
        questions = edit["questions"]
        if not isinstance(questions, list) or not questions or not all(isinstance(q, str) for q in questions):
            return result(AMBIGUOUS, "EMPTY_OR_NON_TEXT")
        for q in questions:
            if not q.strip().endswith("?"):
                return result(AMBIGUOUS, "NOT_A_QUESTION")
            if presentation.is_methodology_note(q):
                return result(AMBIGUOUS, "METHODOLOGY_NOTE_AS_VIEWER_QUESTION")
            if pr.asserts_verification(q) or _FACT_FRAMING.search(q):
                return result(CLAIM_CHANGE, "VERIFICATION_LANGUAGE")
        return result(PRESENTATION_CHANGE, "VIEWER_QUESTIONS", f"{len(questions)} question(s)")

    # set_package_text
    field = edit["field"]
    if field in _PACKAGE_LIST_FIELDS:
        values = edit["value"]
        if not isinstance(values, list) or not values:
            return result(AMBIGUOUS, "EMPTY_OR_NON_TEXT")
        for v in values:
            problem = _text_problem("", v)
            if problem:
                return result(*problem)
        return result(PRESENTATION_CHANGE, "PACKAGE_TEXT", field)
    if field not in _PACKAGE_TEXT_FIELDS:
        return result(AMBIGUOUS, "FIELD_NOT_EDITABLE")
    if field == "youtube_description_draft" and isinstance(edit["value"], str) \
            and "dramatization" not in edit["value"].lower():
        return result(CLAIM_CHANGE, "DISCLOSURE_REMOVED")
    problem = _text_problem(package[field], edit["value"])
    if problem:
        return result(*problem)
    return result(PRESENTATION_CHANGE, "PACKAGE_TEXT", field)


def _apply(package: dict, edit: dict) -> None:
    scenes = {s["scene_id"]: s for s in package["scenes"]}
    op = edit["op"]
    if op == "set_scene_text":
        scenes[edit["scene_id"]][edit["field"]] = edit["value"]
    elif op == "set_narration":
        scenes[edit["scene_id"]]["narration_lines"] = list(edit["lines"])
    elif op == "set_visual_prompts":
        scenes[edit["scene_id"]]["visual_generation_prompts"] = list(edit["prompts"])
    elif op == "set_audio":
        scenes[edit["scene_id"]]["audio"] = {"music": edit["music"], "pacing": edit["pacing"]}
    elif op == "reorder_scenes":
        package["scenes"] = [scenes[i] for i in edit["scene_ids"]]
    elif op == "remove_scene":
        package["scenes"] = [s for s in package["scenes"] if s["scene_id"] != edit["scene_id"]]
    elif op == "set_viewer_questions":
        package["future_intake_questions"] = [{"question": q, "targets": "producer"} for q in edit["questions"]]
    else:
        package[edit["field"]] = copy.deepcopy(edit["value"])
    for order, scene in enumerate(package["scenes"], start=1):
        scene["order"] = order


_FROZEN_PACKAGE_FIELDS = ("schema", "status", "publication_authorized", "generated_media_exists", "intended_audience",
                          "citation_sheet", "disclosures", "experiment_references", "audio_plan", "lineage",
                          "presentation", "governance")
_FROZEN_SCENE_FIELDS = ("scene_id", "label", "audience", "source_refs", "citations", "disclosures",
                        "shot_list", "production_instructions")


def preservation_problems(old: dict, new: dict) -> list:
    """Defense in depth: nothing outside the editable fields may differ."""
    problems = [f"FROZEN_FIELD_CHANGED:{f}" for f in _FROZEN_PACKAGE_FIELDS if old.get(f) != new.get(f)]
    new_scenes = {s["scene_id"]: s for s in new["scenes"]}
    for scene in old["scenes"]:
        if scene["scene_id"] not in new_scenes:
            if scene["audience"] != presentation.INTERNAL_ONLY:
                problems.append(f"VIEWER_SCENE_REMOVED:{scene['scene_id']}")
            continue
        for f in _FROZEN_SCENE_FIELDS:
            if scene[f] != new_scenes[scene["scene_id"]][f]:
                problems.append(f"FROZEN_SCENE_FIELD_CHANGED:{scene['scene_id']}.{f}")
    if set(new_scenes) - {s["scene_id"] for s in old["scenes"]}:
        problems.append("SCENE_ADDED")
    return problems


# ---------------------------------------------------------------------------
# editor
# ---------------------------------------------------------------------------

class PackageEditor:
    def __init__(self, builder: pr.PackageBuilder):
        self.builder = builder
        self.exchange = builder.exchange
        self.governor = builder.runner.governor

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def _record_of(self, package_id: str):
        for meta in self.exchange.all_record_metadata():
            p = meta.get("production_package")
            if p and p["package_id"] == package_id and not meta["erased"]:
                return meta
        return None

    def _successor(self, package_record_id: str):
        for meta in self.exchange.all_record_metadata():
            p = meta.get("production_package")
            if p and p["predecessor_record_id"] == package_record_id and not meta["erased"]:
                return meta["record_id"]
        return None

    def _guard(self, person: str, what: str) -> None:
        if self.governor._active_cycles:
            raise RevisionRefused([f"{what}_DURING_RUNNING_CYCLE"])
        if not isinstance(person, str) or not ep._REVIEWER.match(person):
            raise RevisionRefused([f"UNAUTHORIZED_{what}: a human operator id (operator-<slug>) is required"])

    def revise(self, package_id: str, editor: str, edits, observed_at: str) -> dict:
        self._guard(editor, "EDITOR")
        loaded = self.builder.load(package_id)  # fails closed on tampering
        package, manifest = loaded["package"], loaded["manifest"]
        if self._successor(manifest["package_record_id"]):
            raise RevisionRefused([SUPERSEDED + ": only the latest package version can be revised"])
        candidate_id = package["lineage"]["candidate_id"]
        approval = self.builder._approval(candidate_id)  # candidate must still be approved for production
        if not isinstance(edits, list) or not edits:
            raise RevisionRefused(["NO_EDITS"])
        revised = copy.deepcopy(package)
        classifications = []
        for e in edits:  # each edit is judged against the package as the preceding edits left it
            classifications.append(classify(revised, e))
            if classifications[-1]["class"] == PRESENTATION_CHANGE:
                _apply(revised, e)
        refused = [c for c in classifications if c["class"] != PRESENTATION_CHANGE]
        if refused:
            reasons = [f"{c['class']}:{c['reason']}" for c in refused]
            if any(c["class"] == CLAIM_CHANGE for c in refused):
                reasons.append("RETURN_TO_EPISODE_CANDIDATE_REVISION_AND_HUMAN_REVIEW")
            raise RevisionRefused(reasons, classifications)

        revised["revision"] = {"package_revision": package["revision"]["package_revision"] + 1,
                               "predecessor_package_id": package_id,
                               "predecessor_record_id": manifest["package_record_id"],
                               "editor": editor, "changes": classifications}
        problems = preservation_problems(package, revised) + pr.validate_package(revised)
        if problems:
            raise RevisionRefused(problems, classifications)
        candidate = self.builder._record(candidate_id)
        review = self.builder._record(approval["review_id"])
        c = candidate.payload()
        cited = sorted(set(c["input_record_ids"]) | set(c["lens_output_ids"]) | set(c["contradiction_ids"]))
        records = {rid: self.builder._record(rid) for rid in cited}
        return self.builder._store(revised, candidate, c, approval["review_id"], review.payload(), records, observed_at)

    # -- package review -----------------------------------------------------------------

    def approval_problems(self, package_id: str) -> list:
        meta = self._record_of(package_id)
        if meta is None:
            return ["UNKNOWN_PACKAGE"]
        problems = []
        if self._successor(meta["record_id"]):
            problems.append(SUPERSEDED)
        try:
            self.builder.load(package_id)
            self.builder._approval(meta["production_package"]["candidate_id"])
        except pr.PackageError as exc:
            problems += exc.reasons
        return problems

    def review(self, package_id: str, decision: str, reviewer: str, observed_at: str, notes: str = None) -> str:
        self._guard(reviewer, "REVIEWER")
        meta = self._record_of(package_id)
        if meta is None:
            raise RevisionRefused(["UNKNOWN_PACKAGE"])
        if decision == ep.APPROVED:
            problems = self.approval_problems(package_id)
            if problems:
                raise RevisionRefused(problems)
        receipt = self.exchange.ingest({
            "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_PACKAGE_REVIEW,
            "representation": cxp.REP_PARAPHRASE, "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
            "provenance": cxp.HUMAN_ASSERTED, "privacy": meta["privacy"],
            "payload": {"package_record_id": meta["record_id"], "package_id": package_id, "decision": decision,
                        "reviewer": reviewer, "notes": notes},
            "sources": [], "derived_from": [meta["record_id"]], "verification_ref": None, "consent_ref": None,
            "occurrence": {"emitter_id": reviewer, "observed_at": observed_at, "correlation_id": None,
                           "causation_id": None}})
        if receipt.status == "REJECTED":
            raise RevisionRefused([f"{receipt.error_code}: {receipt.detail}"])
        return receipt.record_id

    def status(self, package_id: str) -> dict:
        """Computed, never stored: an approval counts only for the exact,
        current, intact package version whose candidate is still approved."""
        meta = self._record_of(package_id)
        if meta is None:
            raise RevisionRefused(["UNKNOWN_PACKAGE"])
        reviews = []
        for m in self.exchange.all_record_metadata():
            r = m.get("package_review")
            if r and r["package_id"] == package_id and not m["erased"]:
                problems = self.approval_problems(package_id) if r["decision"] == ep.APPROVED else []
                reviews.append({"review_id": m["record_id"], "decision": r["decision"], "reviewer": r["reviewer"],
                                "valid": not problems, "problems": problems})
        decisions = {r["decision"] for r in reviews}
        if self._successor(meta["record_id"]):
            review_status = SUPERSEDED
        elif ep.REJECTED in decisions:
            review_status = ep.REJECTED
        elif ep.NEEDS_REVISION in decisions:
            review_status = ep.NEEDS_REVISION
        elif any(r["decision"] == ep.APPROVED and r["valid"] for r in reviews):
            review_status = ep.APPROVED
        else:
            review_status = DRAFT
        return {"package_id": package_id, "package_revision": meta["production_package"]["package_revision"],
                "review_status": review_status, "reviews": reviews, "status": pr.DRAFT_PACKAGE,
                "locked_for_production_preparation": review_status == ep.APPROVED,
                "publication_authorized": False, "grants_execution_authority": False}
