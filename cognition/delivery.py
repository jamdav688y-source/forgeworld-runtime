"""FW-ENTERPRISE R2a: governed delivery packages.

A DeliveryPackage is a content-addressed, versioned bundle of arbitrary
artifacts (a production handoff, a report, a CSV -- nothing here assumes
video) for one project and one customer reference. Its lifecycle is never
stored as a flag; it is DERIVED from CXP records every time it is read:

    DRAFT                 DELIVERY_PACKAGE recorded; some machine check failed
    VALIDATED             every machine acceptance check passed
    APPROVED_FOR_HANDOFF  REVIEW_APPROVED (reviewer != editor, who also judged
                          every human-judgement criterion) AND HANDOFF_SIGNED
                          (signer != editor)
    DELIVERED             operator records that exactly the anchored bytes were
                          handed over (sums digest must match). Operator-
                          asserted; it says nothing about receipt or acceptance
    ACCEPTED / REJECTED / REVISION_REQUESTED
                          only from a CUSTOMER_* event that derives from a
                          customer-originated OBSERVATION: provenance OBSERVED,
                          representation QUOTATION, with a source whose locator
                          is customer:<customer_ref>/<package_id>/... . An
                          operator's assertion alone cannot produce these.
  off the main path: RETURNED_FOR_REVISION, REJECTED_IN_REVIEW (review
  decisions) and INVALID (the bundle on disk no longer matches its anchor;
  the recorded status is still reported alongside).

Every step is a DELIVERY_EVENT recorded at most once per package version,
in order, and refused by the exchange if out of order, on a superseded
version, or by the wrong person. A revision is a new package version
(predecessor named, same project/customer/synthetic flag); it supersedes
its predecessor, so no review, signature, delivery or acceptance carries
forward to changed content.

ODCC-1: a package may bind an OUTCOME_SPEC (cognition.destination) fixed
before the work. A bound package cites the spec in its lineage and carries
its project, customer, synthetic flag and acceptance-criteria hash; the
exchange refuses any difference, and refuses a real-customer package with no
spec. Synthetic and internal packages keep the optional-spec behaviour.
ENGAGE-1: a package cannot bind a spec whose engagement consent has been
withdrawn or voided.
IMPORT-1: a package cannot cite a record whose root sources are another
customer's (customer:<ref>/... locators, as imported conversations use).

Synthetic and real work never mix: synthetic=True requires
project-synthetic-* / customer-synthetic-* refs, the SYNTHETIC_FIXTURE
delivery channel and synthetic_fixture customer evidence; synthetic=False
forbids all three.

Not here, by design: payment, invoicing, contract state (cognition.commerce
keeps those, and nothing in this module writes a COMMERCIAL_SIGNAL), email
or upload delivery, customer contact, publication. Identities are
operator-<slug> / customer-<slug> strings checked by pattern and
compared as strings; they are NOT authenticated.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from cognition import bundle, cxp, episode as ep

DELIVERY_SCHEMA = "forgeworld.delivery.package.v1"
DELIVERY_FILE = "delivery.json"
ARTIFACT_DIR = "artifacts"

DRAFT = "DRAFT"
VALIDATED = "VALIDATED"
APPROVED_FOR_HANDOFF = "APPROVED_FOR_HANDOFF"
DELIVERED = "DELIVERED"
ACCEPTED = "ACCEPTED"
REJECTED = "REJECTED"
REVISION_REQUESTED = "REVISION_REQUESTED"
RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
REJECTED_IN_REVIEW = "REJECTED_IN_REVIEW"
INVALID = "INVALID"

REVIEW_APPROVED = "REVIEW_APPROVED"
REVIEW_NEEDS_REVISION = "REVIEW_NEEDS_REVISION"
REVIEW_REJECTED = "REVIEW_REJECTED"
HANDOFF_SIGNED = "HANDOFF_SIGNED"
EV_DELIVERED = "DELIVERED"
CUSTOMER_ACCEPTED = "CUSTOMER_ACCEPTED"
CUSTOMER_REJECTED = "CUSTOMER_REJECTED"
CUSTOMER_REVISION_REQUESTED = "CUSTOMER_REVISION_REQUESTED"
REVIEW_EVENTS = (REVIEW_APPROVED, REVIEW_NEEDS_REVISION, REVIEW_REJECTED)
CUSTOMER_EVENTS = (CUSTOMER_ACCEPTED, CUSTOMER_REJECTED, CUSTOMER_REVISION_REQUESTED)
EVENTS = REVIEW_EVENTS + (HANDOFF_SIGNED, EV_DELIVERED) + CUSTOMER_EVENTS

CHANNEL_SYNTHETIC = "SYNTHETIC_FIXTURE"
CHANNEL_MANUAL = "MANUAL_OUT_OF_BAND"
CHANNELS = (CHANNEL_SYNTHETIC, CHANNEL_MANUAL)

CHECKS = ("artifact_present", "contains_text", "json_keys", "json_equals", "human_judgement")
PASS, FAIL, HUMAN = "PASS", "FAIL", "REQUIRES_HUMAN_JUDGEMENT"

MAX_ARTIFACTS = 64
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_CRITERIA = 32
MAX_LIMITATIONS = 32

_PROJECT = re.compile(r"^project-[a-z0-9][a-z0-9-]{2,62}$")
_CUSTOMER = re.compile(r"^customer-[a-z0-9][a-z0-9-]{2,62}$")
_PACKAGE_ID = re.compile(r"^cxp-dlv-[0-9a-f]{64}$")
_RECORD_ID = re.compile(r"^cxp-rec-[0-9a-f]{64}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CRITERION_ID = re.compile(r"^ac-[a-z0-9][a-z0-9-]{0,40}$")
_ARTIFACT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_MEDIA_TYPES = {".json": "application/json", ".md": "text/markdown", ".csv": "text/csv", ".txt": "text/plain",
                ".svg": "image/svg+xml", ".html": "text/html", ".pdf": "application/pdf", ".png": "image/png"}

_PACKAGE_KEYS_R2A = frozenset({"package_id", "version", "predecessor_package_id", "predecessor_record_id",
                               "project_ref", "customer_ref", "synthetic", "editor_id", "sums_sha256",
                               "delivery_sha256", "source_artifact_ids", "validation_passed",
                               "human_judgement_criteria"})
# ODCC-1 adds the outcome-spec binding; R2a-shaped payloads still parse (replay compatibility)
_PACKAGE_KEYS = _PACKAGE_KEYS_R2A | {"outcome_spec_id", "criteria_sha256"}
_SPEC_ID = re.compile(r"^cxp-osp-[0-9a-f]{64}$")
_EVENT_KEYS = frozenset({"package_record_id", "package_id", "event", "actor_id", "criteria_judged",
                         "delivered_sums_sha256", "channel", "evidence_record_id", "document_digest", "notes"})
# event -> payload fields that must be non-null (all others except notes must be null)
_EVENT_FIELDS = {REVIEW_APPROVED: ("criteria_judged",), REVIEW_NEEDS_REVISION: (), REVIEW_REJECTED: (),
                 HANDOFF_SIGNED: (), EV_DELIVERED: ("delivered_sums_sha256", "channel"),
                 **{e: ("evidence_record_id", "document_digest") for e in CUSTOMER_EVENTS}}
_OPTIONAL_EVENT_FIELDS = ("criteria_judged", "delivered_sums_sha256", "channel", "evidence_record_id", "document_digest")
_HUMAN_LABELS = (cxp.HUMAN_ASSERTED, cxp.REP_PARAPHRASE, cxp.EV_NONE, cxp.VER_UNVERIFIED)


class DeliveryRefused(Exception):
    def __init__(self, reasons):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)


def customer_refs_of(meta: dict) -> set:
    """Customer refs named by a record's root-source locators (customer:<ref>/...);
    the convention imported conversations and customer evidence use."""
    return {s["locator"].split("/", 1)[0][len("customer:"):] for s in meta.get("root_sources", ())
            if s["locator"].startswith("customer:")}


def media_type(name: str) -> str:
    return _MEDIA_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")


def criteria_sha256(criteria) -> str:
    return bundle.sha256_hex(cxp.canonical_bytes(criteria))


def _text(value, what: str) -> None:
    from cognition import commerce  # its free-text guard refuses contact and banking data
    try:
        commerce._check_summary(value)
    except cxp.CXPError as exc:
        raise cxp.CXPError(exc.code, f"{what}: {exc.detail}") from None


def ref_problems(project_ref, customer_ref, synthetic) -> list:
    problems = []
    if not isinstance(project_ref, str) or not _PROJECT.match(project_ref):
        problems.append("MALFORMED_PROJECT_REF")
    if not isinstance(customer_ref, str) or not _CUSTOMER.match(customer_ref):
        problems.append("MALFORMED_CUSTOMER_REF")
    if not isinstance(synthetic, bool):
        problems.append("SYNTHETIC_FLAG_REQUIRED")
    if problems:
        return problems
    marked = (project_ref.startswith("project-synthetic-"), customer_ref.startswith("customer-synthetic-"))
    if synthetic and marked != (True, True):
        problems.append("SYNTHETIC_REFS_REQUIRED: synthetic work uses project-synthetic-* and customer-synthetic-*")
    if not synthetic and ("synthetic" in project_ref or "synthetic" in customer_ref):
        problems.append("SYNTHETIC_REF_ON_REAL_PACKAGE")
    return problems


# ---------------------------------------------------------------------------
# DELIVERY_PACKAGE / DELIVERY_EVENT record rules (called by cxp / exchange)
# ---------------------------------------------------------------------------

def check_package_payload(payload: dict) -> None:
    if set(payload) not in (_PACKAGE_KEYS, _PACKAGE_KEYS_R2A):
        raise cxp.CXPError(cxp.E_MALFORMED, f"DELIVERY_PACKAGE payload requires exactly {sorted(_PACKAGE_KEYS)}")
    if "criteria_sha256" in payload:
        if not isinstance(payload["criteria_sha256"], str) or not _SHA256.match(payload["criteria_sha256"]):
            raise cxp.CXPError(cxp.E_MALFORMED, "criteria_sha256 must be a sha256 hex digest")
        if payload["outcome_spec_id"] is not None and not (
                isinstance(payload["outcome_spec_id"], str) and _SPEC_ID.match(payload["outcome_spec_id"])):
            raise cxp.CXPError(cxp.E_MALFORMED, "outcome_spec_id is malformed")
    if not isinstance(payload["package_id"], str) or not _PACKAGE_ID.match(payload["package_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "package_id is malformed")
    problems = ref_problems(payload["project_ref"], payload["customer_ref"], payload["synthetic"])
    if problems:
        raise cxp.CXPError(cxp.E_MALFORMED, problems[0])
    if not isinstance(payload["editor_id"], str) or not ep._REVIEWER.match(payload["editor_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "editor_id must be a human operator id (operator-<slug>)")
    for name in ("sums_sha256", "delivery_sha256"):
        if not isinstance(payload[name], str) or not _SHA256.match(payload[name]):
            raise cxp.CXPError(cxp.E_MALFORMED, f"{name} must be a sha256 hex digest")
    sources = payload["source_artifact_ids"]
    if (not isinstance(sources, list) or not sources or sources != sorted(set(sources))
            or not all(isinstance(s, str) and _RECORD_ID.match(s) for s in sources)):
        raise cxp.CXPError(cxp.E_MALFORMED, "source_artifact_ids must be a sorted, non-empty list of record ids")
    if not isinstance(payload["validation_passed"], bool):
        raise cxp.CXPError(cxp.E_MALFORMED, "validation_passed must be a boolean")
    judged = payload["human_judgement_criteria"]
    if (not isinstance(judged, list) or judged != sorted(set(judged))
            or not all(isinstance(c, str) and _CRITERION_ID.match(c) for c in judged)):
        raise cxp.CXPError(cxp.E_MALFORMED, "human_judgement_criteria must be a sorted list of criterion ids")
    version = payload["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise cxp.CXPError(cxp.E_MALFORMED, "version must be a positive integer")
    chain = (payload["predecessor_package_id"], payload["predecessor_record_id"])
    if version == 1:
        if chain != (None, None):
            raise cxp.CXPError(cxp.E_MALFORMED, "a first version has no predecessor")
    elif not (isinstance(chain[0], str) and _PACKAGE_ID.match(chain[0])
              and isinstance(chain[1], str) and _RECORD_ID.match(chain[1])):
        raise cxp.CXPError(cxp.E_MALFORMED, "a later version names its predecessor package and record")


def check_package_labels(payload, provenance, representation, evidence, verification, derived_from) -> None:
    if (provenance, representation, evidence, verification) != _HUMAN_LABELS:
        raise cxp.CXPError(cxp.E_KIND_RULE, "a DELIVERY_PACKAGE is assembled by a human: HUMAN_ASSERTED, PARAPHRASE, "
                                            "NONE, UNVERIFIED -- packaging adds no evidence")
    expected = set(payload["source_artifact_ids"]) | ({payload["predecessor_record_id"]} - {None})
    if list(derived_from) != sorted(expected):
        raise cxp.CXPError(cxp.E_KIND_RULE, "a DELIVERY_PACKAGE derives from exactly its source artifacts and, "
                                            "for a revision, its predecessor")


def check_event_payload(payload: dict) -> None:
    if set(payload) != _EVENT_KEYS:
        raise cxp.CXPError(cxp.E_MALFORMED, f"DELIVERY_EVENT payload requires exactly {sorted(_EVENT_KEYS)}")
    event = payload["event"]
    if event not in EVENTS:
        raise cxp.CXPError(cxp.E_MALFORMED, f"event must be one of {EVENTS}")
    if not isinstance(payload["package_record_id"], str) or not _RECORD_ID.match(payload["package_record_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "package_record_id must be a record id")
    if not isinstance(payload["package_id"], str) or not _PACKAGE_ID.match(payload["package_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "package_id is malformed")
    if not isinstance(payload["actor_id"], str) or not ep._REVIEWER.match(payload["actor_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "actor_id must be a human operator id (operator-<slug>)")
    required = _EVENT_FIELDS[event]
    for name in _OPTIONAL_EVENT_FIELDS:
        if (payload[name] is None) == (name in required):
            raise cxp.CXPError(cxp.E_MALFORMED, f"{event} {'requires' if name in required else 'must not carry'} {name}")
    judged = payload["criteria_judged"]
    if judged is not None and (not isinstance(judged, list) or judged != sorted(set(judged))
                               or not all(isinstance(c, str) and _CRITERION_ID.match(c) for c in judged)):
        raise cxp.CXPError(cxp.E_MALFORMED, "criteria_judged must be a sorted list of criterion ids")
    if payload["delivered_sums_sha256"] is not None and not (
            isinstance(payload["delivered_sums_sha256"], str) and _SHA256.match(payload["delivered_sums_sha256"])):
        raise cxp.CXPError(cxp.E_MALFORMED, "delivered_sums_sha256 must be a sha256 hex digest")
    if payload["channel"] is not None and payload["channel"] not in CHANNELS:
        raise cxp.CXPError(cxp.E_MALFORMED, f"channel must be one of {CHANNELS}")
    if payload["evidence_record_id"] is not None and not (
            isinstance(payload["evidence_record_id"], str) and _RECORD_ID.match(payload["evidence_record_id"])):
        raise cxp.CXPError(cxp.E_MALFORMED, "evidence_record_id must be a record id")
    if payload["document_digest"] is not None and not (
            isinstance(payload["document_digest"], str) and _DIGEST.match(payload["document_digest"])):
        raise cxp.CXPError(cxp.E_MALFORMED, "document_digest must be sha256:<64 hex>")
    if payload["notes"] is not None:
        _text(payload["notes"], "notes")


def check_event_labels(payload, provenance, representation, evidence, verification, derived_from) -> None:
    if (provenance, representation, evidence, verification) != _HUMAN_LABELS:
        raise cxp.CXPError(cxp.E_KIND_RULE, "a DELIVERY_EVENT is recorded by a human operator: HUMAN_ASSERTED, "
                                            "PARAPHRASE, NONE, UNVERIFIED")
    expected = {payload["package_record_id"]} | ({payload["evidence_record_id"]} - {None})
    if list(derived_from) != sorted(expected):
        raise cxp.CXPError(cxp.E_KIND_RULE, "a DELIVERY_EVENT derives from exactly its package version and, for a "
                                            "customer outcome, the customer evidence")


def package_metadata(payload: dict) -> dict:
    return {k: payload.get(k) for k in ("package_id", "version", "predecessor_record_id", "project_ref", "customer_ref",
                                        "synthetic", "editor_id", "sums_sha256", "validation_passed",
                                        "human_judgement_criteria", "outcome_spec_id", "criteria_sha256")}


def event_metadata(payload: dict) -> dict:
    return {k: payload[k] for k in ("package_record_id", "package_id", "event", "actor_id", "criteria_judged",
                                    "delivered_sums_sha256", "channel", "evidence_record_id", "document_digest")}


def _refuse(detail: str):
    raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, detail)


def _live(records: dict):
    return [m for m in records.values() if not m["erased"]]


def check_package_transition(payload: dict, lookup, records: dict) -> None:
    spec_id = payload.get("outcome_spec_id")
    bound = None
    for rid in payload["source_artifact_ids"]:
        meta = lookup(rid)
        if meta["kind"] in (cxp.KIND_DELIVERY_PACKAGE, cxp.KIND_DELIVERY_EVENT):
            _refuse("a delivery package's source artifacts are work records, not delivery records")
        if meta["kind"] == cxp.KIND_OUTCOME_SPEC:
            if meta["outcome_spec"]["spec_id"] != spec_id:
                _refuse("a package cites an outcome spec it is not bound to")
            bound = meta["outcome_spec"]
    if spec_id is not None:
        if bound is None:
            _refuse("the bound outcome spec is absent from the package's source lineage")
        for field in ("project_ref", "customer_ref", "synthetic"):
            if bound[field] != payload[field]:
                _refuse(f"the package's {field} differs from its outcome spec")
        if bound["criteria_sha256"] != payload["criteria_sha256"]:
            _refuse("the package's acceptance criteria differ from its outcome spec")
        if bound.get("consent_record_id"):
            from cognition import destination  # deferred: destination builds on this module
            problems = destination.consent_problems(bound["consent_record_id"], bound["engagement_ref"], lookup, records)
            if problems:
                _refuse(f"the outcome spec's consent no longer stands: {problems[0]}")
    elif not payload["synthetic"]:
        _refuse("a real customer package requires an outcome specification")
    if any(customer_refs_of(lookup(rid)) - {payload["customer_ref"]} for rid in payload["source_artifact_ids"]):
        _refuse("a package cannot cite another customer's evidence")
    previous = payload["predecessor_record_id"]
    if previous is None:
        return
    prior = lookup(previous)
    if prior is None or prior["kind"] != cxp.KIND_DELIVERY_PACKAGE or prior["erased"]:
        _refuse("predecessor_record_id is not an accepted DELIVERY_PACKAGE")
    p = prior["delivery_package"]
    if (p["package_id"] != payload["predecessor_package_id"] or p["version"] + 1 != payload["version"]
            or (p["project_ref"], p["customer_ref"], p["synthetic"])
            != (payload["project_ref"], payload["customer_ref"], payload["synthetic"])):
        _refuse("a revision follows the previous version of the same project, customer and synthetic flag")
    if p.get("outcome_spec_id") != spec_id:
        _refuse("a revision keeps its predecessor's outcome spec")
    if any((m.get("delivery_package") or {}).get("predecessor_record_id") == previous for m in _live(records)):
        _refuse("that package version has already been revised")


def check_event_transition(payload: dict, lookup, records: dict) -> None:
    package = lookup(payload["package_record_id"])
    if (package is None or package["kind"] != cxp.KIND_DELIVERY_PACKAGE or package["erased"]
            or package["delivery_package"]["package_id"] != payload["package_id"]):
        _refuse("an event must target that exact DELIVERY_PACKAGE version")
    p = package["delivery_package"]
    live = _live(records)
    if any((m.get("delivery_package") or {}).get("predecessor_record_id") == payload["package_record_id"] for m in live):
        _refuse("that package version has been superseded")
    done = {m["delivery_event"]["event"]: m["delivery_event"] for m in live
            if (m.get("delivery_event") or {}).get("package_record_id") == payload["package_record_id"]}
    event, actor = payload["event"], payload["actor_id"]

    if event in REVIEW_EVENTS:
        if set(done) & set(REVIEW_EVENTS):
            _refuse("this package version has already been reviewed")
        if actor == p["editor_id"]:
            _refuse("the editor of a package version cannot review it")
        if event == REVIEW_APPROVED:
            if not p["validation_passed"]:
                _refuse("a package whose machine acceptance checks failed cannot be approved")
            if payload["criteria_judged"] != p["human_judgement_criteria"]:
                _refuse("approval must judge exactly the package's human-judgement criteria")
    elif event == HANDOFF_SIGNED:
        if REVIEW_APPROVED not in done:
            _refuse("handoff needs an approving review of this exact version")
        if HANDOFF_SIGNED in done:
            _refuse("this package version has already been signed off")
        if actor == p["editor_id"]:
            _refuse("the editor of a package version cannot sign its handoff")
    elif event == EV_DELIVERED:
        if HANDOFF_SIGNED not in done:
            _refuse("delivery needs a signed handoff of this exact version")
        if EV_DELIVERED in done:
            _refuse("this package version has already been recorded as delivered")
        if payload["delivered_sums_sha256"] != p["sums_sha256"]:
            _refuse("the delivered checksum list is not the one anchored for this version")
        if (payload["channel"] == CHANNEL_SYNTHETIC) != p["synthetic"]:
            _refuse("synthetic packages use the SYNTHETIC_FIXTURE channel, and only they do")
    else:  # customer outcome
        if EV_DELIVERED not in done:
            _refuse("a customer outcome needs a recorded delivery of this exact version")
        if set(done) & set(CUSTOMER_EVENTS):
            _refuse("this package version already has a customer outcome")
        evidence = lookup(payload["evidence_record_id"])
        if evidence is None or evidence["erased"] or evidence["kind"] != cxp.KIND_OBSERVATION:
            _refuse("customer outcomes need customer evidence recorded as an OBSERVATION")
        if (evidence["provenance"], evidence["representation"]) != (cxp.OBSERVED, cxp.REP_QUOTATION):
            _refuse("customer evidence must be the customer's own words, observed and quoted -- an operator "
                    "assertion is not customer evidence")
        prefix = f"customer:{p['customer_ref']}/{p['package_id']}/"
        source_type = "synthetic_fixture" if p["synthetic"] else "document"
        if not any(s["locator"].startswith(prefix) and s["source_type"] == source_type
                   for s in evidence["root_sources"]):
            _refuse(f"customer evidence must cite a {source_type} source located at {prefix}...")


# ---------------------------------------------------------------------------
# acceptance criteria (fixed, deterministic vocabulary)
# ---------------------------------------------------------------------------

def criteria_problems(criteria) -> list:
    if not isinstance(criteria, list) or not criteria or len(criteria) > MAX_CRITERIA:
        return [f"ACCEPTANCE_CRITERIA_REQUIRED: 1..{MAX_CRITERIA} criteria"]
    problems, seen = [], set()
    shapes = {"artifact_present": {"path"}, "contains_text": {"path", "text"}, "json_keys": {"path", "keys"},
              "json_equals": {"path", "key", "value"}, "human_judgement": set()}
    for c in criteria:
        if not isinstance(c, dict) or c.get("check") not in CHECKS:
            problems.append("UNKNOWN_CRITERION_CHECK")
            continue
        if set(c) != {"criterion_id", "description", "check"} | shapes[c["check"]]:
            problems.append(f"MALFORMED_CRITERION:{c.get('criterion_id')}")
        elif not isinstance(c["criterion_id"], str) or not _CRITERION_ID.match(c["criterion_id"]) or c["criterion_id"] in seen:
            problems.append("CRITERION_ID_MALFORMED_OR_DUPLICATE")
        else:
            seen.add(c["criterion_id"])
            try:
                _text(c["description"], "description")
            except cxp.CXPError:
                problems.append(f"CRITERION_DESCRIPTION_REFUSED:{c['criterion_id']}")
    return problems


def evaluate(criteria: list, artifacts: dict) -> list:
    """artifacts: {artifact name: bytes}. Deterministic; reads nothing else."""
    results = []
    for c in criteria:
        check, result, detail = c["check"], FAIL, ""
        data = artifacts.get(c.get("path"))
        if check == "human_judgement":
            result, detail = HUMAN, "judged by the reviewer, not by a machine"
        elif data is None:
            detail = "artifact missing"
        elif check == "artifact_present":
            result = PASS
        elif check == "contains_text":
            result = PASS if c["text"] in data.decode("utf-8", "replace") else FAIL
        else:
            try:
                doc = json.loads(data)
            except ValueError:
                doc, detail = None, "not JSON"
            if isinstance(doc, dict) and check == "json_keys":
                result = PASS if set(c["keys"]) <= set(doc) else FAIL
            elif isinstance(doc, dict):
                result = PASS if c["key"] in doc and doc[c["key"]] == c["value"] else FAIL
        results.append({"criterion_id": c["criterion_id"], "check": check, "result": result, "detail": detail})
    return results


# ---------------------------------------------------------------------------
# the desk: assemble, record decisions, derive status, verify
# ---------------------------------------------------------------------------

class DeliveryDesk:
    def __init__(self, exchange, governor, root: Path):
        self.exchange = exchange
        self.governor = governor
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def _guard(self, person, what: str) -> None:
        if self.governor._active_cycles:
            raise DeliveryRefused([f"{what}_DURING_RUNNING_CYCLE"])
        if not isinstance(person, str) or not ep._REVIEWER.match(person):
            raise DeliveryRefused([f"UNAUTHORIZED_{what}: a human operator id (operator-<slug>) is required"])

    def _index(self) -> tuple:
        packages, events = {}, {}
        for meta in self.exchange.all_record_metadata():
            if meta["erased"]:
                continue
            if "delivery_package" in meta:
                packages[meta["record_id"]] = meta
            elif "delivery_event" in meta:
                events.setdefault(meta["delivery_event"]["package_record_id"], {})[meta["delivery_event"]["event"]] = meta
        return packages, events

    def _record_of(self, package_id: str):
        packages, _ = self._index()
        return next((m for m in packages.values() if m["delivery_package"]["package_id"] == package_id), None)

    def _successor(self, record_id: str):
        packages, _ = self._index()
        return next((m["delivery_package"]["package_id"] for m in packages.values()
                     if m["delivery_package"]["predecessor_record_id"] == record_id), None)

    # -- assembly -------------------------------------------------------------------

    def assemble(self, *, project_ref, customer_ref, synthetic, editor_id, artifacts: dict, source_artifact_ids,
                 acceptance_criteria, known_limitations, created_at: str, predecessor_package_id=None,
                 descriptions=None, outcome_spec_id=None) -> dict:
        self._guard(editor_id, "EDITOR")
        problems = ref_problems(project_ref, customer_ref, synthetic)
        spec_record_id = None
        if outcome_spec_id is not None:
            spec_record_id, spec_problems = self._spec_problems(outcome_spec_id, project_ref, customer_ref, synthetic,
                                                                acceptance_criteria, artifacts, known_limitations)
            problems += spec_problems
        elif synthetic is False:
            problems.append("OUTCOME_SPEC_REQUIRED: a real customer package binds to an outcome specification")
        if not isinstance(artifacts, dict) or not artifacts or len(artifacts) > MAX_ARTIFACTS:
            problems.append(f"ARTIFACTS_REQUIRED: 1..{MAX_ARTIFACTS} artifacts")
            artifacts = {}
        for name, data in sorted(artifacts.items()):
            if not isinstance(name, str) or not _ARTIFACT_NAME.match(name):
                problems.append(f"INVALID_ARTIFACT_NAME:{name}")
            elif not isinstance(data, bytes):
                problems.append(f"MISSING_ARTIFACT:{name}")
            elif len(data) > MAX_ARTIFACT_BYTES:
                problems.append(f"ARTIFACT_TOO_LARGE:{name}")
        sources = sorted(set(source_artifact_ids or ()) | ({spec_record_id} - {None}))
        if not sources:
            problems.append("SOURCE_ARTIFACTS_REQUIRED")
        for rid in sources:
            meta = self.exchange.record_metadata(rid) if isinstance(rid, str) and _RECORD_ID.match(rid) else None
            if meta is None or meta["erased"]:
                problems.append(f"MISSING_SOURCE_ARTIFACT:{rid}")
        problems += criteria_problems(acceptance_criteria)
        limitations = list(known_limitations or ())
        if len(limitations) > MAX_LIMITATIONS:
            problems.append("TOO_MANY_LIMITATIONS")
        for text in limitations + list((descriptions or {}).values()):
            try:
                _text(text, "text")
            except cxp.CXPError:
                problems.append("TEXT_REFUSED: limitations and descriptions must be short and free of contact data")
        version, predecessor_record_id = 1, None
        if predecessor_package_id is not None:
            prior = self._record_of(predecessor_package_id)
            if prior is None:
                problems.append("UNKNOWN_PREDECESSOR")
            else:
                p = prior["delivery_package"]
                if self._successor(prior["record_id"]):
                    problems.append("PREDECESSOR_SUPERSEDED: only the latest version can be revised")
                if (p["project_ref"], p["customer_ref"], p["synthetic"]) != (project_ref, customer_ref, synthetic):
                    problems.append("REVISION_CHANGES_PROJECT_CUSTOMER_OR_SYNTHETIC_FLAG")
                version, predecessor_record_id = p["version"] + 1, prior["record_id"]
        if problems:
            raise DeliveryRefused(problems)

        results = evaluate(acceptance_criteria, artifacts)
        descriptions = descriptions or {}
        body = {
            "schema": DELIVERY_SCHEMA, "project_ref": project_ref, "customer_ref": customer_ref, "synthetic": synthetic,
            "version": version, "predecessor_package_id": predecessor_package_id, "editor_id": editor_id,
            "created_at": created_at, "source_artifact_ids": sources,
            "artifact_manifest": [{"path": f"{ARTIFACT_DIR}/{name}", "sha256": bundle.sha256_hex(artifacts[name]),
                                   "bytes": len(artifacts[name]),
                                   "media_type": media_type(name),
                                   "description": descriptions.get(name)} for name in sorted(artifacts)],
            "checksums": {"file": bundle.SUMS, "algorithm": "sha256",
                          "anchor": "sha256(SHA256SUMS) is recorded in this version's DELIVERY_PACKAGE record"},
            "acceptance_criteria": acceptance_criteria, "criteria_sha256": criteria_sha256(acceptance_criteria),
            "outcome_spec_id": outcome_spec_id, "validation_results": results,
            "known_limitations": limitations,
            "statements": {"delivery_is_not_acceptance": True, "acceptance_is_not_payment": True,
                           "identities_are_not_authenticated": True, "publication_authorized": False},
        }
        package_id = cxp.digest_id("delivery", body)
        files = {f"{ARTIFACT_DIR}/{name}": artifacts[name] for name in artifacts}
        files[DELIVERY_FILE] = cxp.canonical_bytes(body)
        files[bundle.SUMS] = bundle.render_sums(files)
        try:
            directory = bundle.write(self.root, package_id, files)
        except bundle.BundleError as exc:
            raise DeliveryRefused(exc.reasons) from None
        payload = {"package_id": package_id, "version": version, "predecessor_package_id": predecessor_package_id,
                   "predecessor_record_id": predecessor_record_id, "project_ref": project_ref,
                   "customer_ref": customer_ref, "synthetic": synthetic, "editor_id": editor_id,
                   "sums_sha256": bundle.sha256_hex(files[bundle.SUMS]),
                   "delivery_sha256": bundle.sha256_hex(files[DELIVERY_FILE]), "source_artifact_ids": sources,
                   "validation_passed": all(r["result"] != FAIL for r in results),
                   "human_judgement_criteria": sorted(r["criterion_id"] for r in results if r["result"] == HUMAN),
                   "outcome_spec_id": outcome_spec_id, "criteria_sha256": criteria_sha256(acceptance_criteria)}
        receipt = self._ingest(cxp.KIND_DELIVERY_PACKAGE, payload,
                               sorted(set(sources) | ({predecessor_record_id} - {None})), editor_id, created_at)
        if receipt.status == "REJECTED":
            shutil.rmtree(directory, ignore_errors=True)
            raise DeliveryRefused([f"{receipt.error_code}: {receipt.detail}"])
        return {"package_id": package_id, "package_record_id": receipt.record_id, "directory": str(directory),
                "delivery": body, "sums": files[bundle.SUMS].decode("ascii")}

    def _spec_problems(self, spec_id, project_ref, customer_ref, synthetic, criteria, artifacts, limitations):
        meta = next((m for m in self.exchange.all_record_metadata()
                     if not m["erased"] and (m.get("outcome_spec") or {}).get("spec_id") == spec_id), None)
        if meta is None:
            return None, ["UNKNOWN_OUTCOME_SPEC"]
        spec = self.exchange.get_record(meta["record_id"]).payload()
        problems = [f"OUTCOME_SPEC_MISMATCH:{field}" for field, value in
                    (("project_ref", project_ref), ("customer_ref", customer_ref), ("synthetic", synthetic))
                    if spec[field] != value]
        if criteria != spec["acceptance_criteria"]:
            problems.append("CRITERIA_DIFFER_FROM_OUTCOME_SPEC")
        for d in spec["required_deliverables"]:
            if not isinstance(artifacts, dict) or d["name"] not in artifacts:
                problems.append(f"MISSING_REQUIRED_DELIVERABLE:{d['name']}")
        for disclosure in spec["disclosures"]:
            if disclosure not in (limitations or ()):
                problems.append("MISSING_REQUIRED_DISCLOSURE")
        if spec.get("consent_record_id"):
            from cognition import destination
            metas = {m["record_id"]: m for m in self.exchange.all_record_metadata()}
            problems += destination.consent_problems(spec["consent_record_id"], spec["engagement_ref"], metas.get, metas)
        return meta["record_id"], problems

    def _ingest(self, kind, payload, derived_from, emitter, observed_at):
        return self.exchange.ingest({
            "schema_version": cxp.SCHEMA_VERSION, "kind": kind, "representation": cxp.REP_PARAPHRASE,
            "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.HUMAN_ASSERTED,
            "privacy": cxp.PRIV_INTERNAL, "payload": payload, "sources": [], "derived_from": derived_from,
            "verification_ref": None, "consent_ref": None,
            "occurrence": {"emitter_id": emitter, "observed_at": observed_at, "correlation_id": None,
                           "causation_id": None}})

    # -- lifecycle events -------------------------------------------------------------

    def _event(self, package_id: str, event: str, actor_id, observed_at: str, notes=None, **fields) -> str:
        self._guard(actor_id, "ACTOR")
        meta = self._record_of(package_id)
        if meta is None:
            raise DeliveryRefused(["UNKNOWN_PACKAGE"])
        integrity = self.verify(package_id)["integrity_problems"]
        if integrity:  # no decision is recorded about bytes that are not the anchored ones
            raise DeliveryRefused(["PACKAGE_INTEGRITY_FAILED"] + integrity)
        payload = {"package_record_id": meta["record_id"], "package_id": package_id, "event": event,
                   "actor_id": actor_id, "notes": notes, **{k: None for k in _OPTIONAL_EVENT_FIELDS}, **fields}
        derived = sorted({meta["record_id"]} | ({fields.get("evidence_record_id")} - {None}))
        receipt = self._ingest(cxp.KIND_DELIVERY_EVENT, payload, derived, actor_id, observed_at)
        if receipt.status == "REJECTED":
            raise DeliveryRefused([f"{receipt.error_code}: {receipt.detail}"])
        return receipt.record_id

    def review(self, package_id, reviewer_id, decision, observed_at, criteria_judged=(), notes=None) -> str:
        event = {ep.APPROVED: REVIEW_APPROVED, ep.NEEDS_REVISION: REVIEW_NEEDS_REVISION,
                 ep.REJECTED: REVIEW_REJECTED}.get(decision)
        if event is None:
            raise DeliveryRefused([f"UNKNOWN_DECISION: one of {ep.DECISIONS}"])
        fields = {"criteria_judged": sorted(set(criteria_judged))} if event == REVIEW_APPROVED else {}
        return self._event(package_id, event, reviewer_id, observed_at, notes, **fields)

    def sign_handoff(self, package_id, signer_id, observed_at, notes=None) -> str:
        return self._event(package_id, HANDOFF_SIGNED, signer_id, observed_at, notes)

    def record_delivery(self, package_id, actor_id, channel, observed_at, notes=None) -> str:
        meta = self._record_of(package_id)
        sums = meta["delivery_package"]["sums_sha256"] if meta else None
        return self._event(package_id, EV_DELIVERED, actor_id, observed_at, notes,
                           delivered_sums_sha256=sums, channel=channel)

    def record_customer_outcome(self, package_id, actor_id, outcome, evidence_record_id, document_digest,
                                observed_at, notes=None) -> str:
        if outcome not in CUSTOMER_EVENTS:
            raise DeliveryRefused([f"UNKNOWN_OUTCOME: one of {CUSTOMER_EVENTS}"])
        return self._event(package_id, outcome, actor_id, observed_at, notes,
                           evidence_record_id=evidence_record_id, document_digest=document_digest)

    # -- derived view -------------------------------------------------------------------

    def verify(self, package_id: str) -> dict:
        meta = self._record_of(package_id)
        anchored = meta["delivery_package"]["sums_sha256"] if meta else None
        present = bundle.read(self.root / package_id)
        problems = [] if meta else ["NOT_ANCHORED"]
        body = None
        if present is not None and DELIVERY_FILE in present:
            try:
                body = json.loads(present[DELIVERY_FILE])
            except ValueError:
                problems.append("DELIVERY_RECORD_UNREADABLE")
        expected = (DELIVERY_FILE, bundle.SUMS) + tuple(a["path"] for a in (body or {}).get("artifact_manifest", ()))
        problems += bundle.check(present, expected, anchored)
        if isinstance(body, dict):
            if cxp.digest_id("delivery", body) != package_id:
                problems.append("PACKAGE_ID_MISMATCH")
            elif present is not None and [a["sha256"] for a in body["artifact_manifest"]] != [
                    bundle.sha256_hex(present.get(a["path"], b"")) for a in body["artifact_manifest"]]:
                problems.append("ARTIFACT_MANIFEST_MISMATCH")
            elif meta and meta["delivery_package"].get("criteria_sha256") not in (
                    None, criteria_sha256(body["acceptance_criteria"])):
                problems.append("CRITERIA_HASH_MISMATCH")
            elif present is not None and evaluate(body["acceptance_criteria"], {
                    a["path"][len(ARTIFACT_DIR) + 1:]: present[a["path"]] for a in body["artifact_manifest"]}) != body["validation_results"]:
                problems.append("VALIDATION_RESULTS_DO_NOT_REPRODUCE")
        return {"package_id": package_id, "intact": not problems, "integrity_problems": problems}

    def load(self, package_id: str) -> dict:
        problems = self.verify(package_id)["integrity_problems"]
        if problems:
            raise DeliveryRefused(["PACKAGE_INTEGRITY_FAILED"] + problems)
        return json.loads((self.root / package_id / DELIVERY_FILE).read_bytes())

    def status(self, package_id: str) -> dict:
        packages, events = self._index()
        meta = next((m for m in packages.values() if m["delivery_package"]["package_id"] == package_id), None)
        if meta is None:
            raise DeliveryRefused(["UNKNOWN_PACKAGE"])
        p = meta["delivery_package"]
        done = {name: m["delivery_event"] | {"record_id": m["record_id"]}
                for name, m in events.get(meta["record_id"], {}).items()}
        outcome = next((e for e in CUSTOMER_EVENTS if e in done), None)
        if outcome:
            recorded = {CUSTOMER_ACCEPTED: ACCEPTED, CUSTOMER_REJECTED: REJECTED,
                        CUSTOMER_REVISION_REQUESTED: REVISION_REQUESTED}[outcome]
        elif EV_DELIVERED in done:
            recorded = DELIVERED
        elif HANDOFF_SIGNED in done:
            recorded = APPROVED_FOR_HANDOFF
        elif REVIEW_NEEDS_REVISION in done:
            recorded = RETURNED_FOR_REVISION
        elif REVIEW_REJECTED in done:
            recorded = REJECTED_IN_REVIEW
        else:
            recorded = VALIDATED if p["validation_passed"] else DRAFT
        integrity = self.verify(package_id)
        review = next((done[e] for e in REVIEW_EVENTS if e in done), None)
        successor = next((m["delivery_package"]["package_id"] for m in packages.values()
                          if m["delivery_package"]["predecessor_record_id"] == meta["record_id"]), None)
        return {
            "package_id": package_id, "package_record_id": meta["record_id"], "version": p["version"],
            "project_ref": p["project_ref"], "customer_ref": p["customer_ref"], "synthetic": p["synthetic"],
            "status": recorded if integrity["intact"] else INVALID, "recorded_status": recorded,
            "intact": integrity["intact"], "integrity_problems": integrity["integrity_problems"],
            "current": successor is None, "superseded_by": successor,
            "editor_id": p["editor_id"], "reviewer_id": review["actor_id"] if review else None,
            "review_event": review["event"] if review else None,
            "signer_id": done[HANDOFF_SIGNED]["actor_id"] if HANDOFF_SIGNED in done else None,
            "delivery": ({"actor_id": done[EV_DELIVERED]["actor_id"], "channel": done[EV_DELIVERED]["channel"],
                          "operator_asserted": True, "receipt_confirmed_by_customer": False}
                         if EV_DELIVERED in done else None),
            "customer_outcome": ({"event": outcome, "evidence_record_id": done[outcome]["evidence_record_id"],
                                  "document_digest": done[outcome]["document_digest"],
                                  "recorded_by": done[outcome]["actor_id"]} if outcome else None),
            "history": [{"event": e, "actor_id": done[e]["actor_id"], "record_id": done[e]["record_id"]}
                        for e in EVENTS if e in done],
            "identities_authenticated": False, "payment_recorded": False, "publication_authorized": False,
        }
