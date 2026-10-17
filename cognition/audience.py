"""FW-S1-AUDIENCE-INTELLIGENCE-001: audience signal intake.

An AUDIENCE_QUESTION is a CXP ROOT record: one question someone asked on
YOUTUBE, FACEBOOK or LINKEDIN, imported from material a human supplied by
hand (an export, a transcription) or from a synthetic fixture. There is no
connector, scraper or API here, and "scraped" or API-sourced material has
no acquisition value to be filed under.

TWO IDENTITY SYSTEMS, kept apart
  topic_id     what was asked: a digest of the question text alone. Two
               people asking the same words share it, and R4 builds cycle_id
               from it, so they are ONE research topic. (CXP content_id is
               not used for this: it also covers the per-event provenance
               this payload carries.)
  record_id    (CXP) this question from this platform event. The source
               locator is "<platform>:<platform_event_ref>", so two
               distinct comments with equal text are two records, while
               re-importing the same event is the same record.
  occurrence   (CXP) one import of it: the import batch is the occurrence
               correlation_id and imported_at its observed_at, so neither
               ever changes record identity. A repeated import is reported
               DUPLICATE_IMPORT and never re-processed.
  origin       (the source's independence_key) what corroboration counts.
               In order: an operator-declared origin_ref (e.g. a known
               cross-post); a repost's ORIGINAL's origin; the per-platform
               author pseudonym; the platform event itself. A thousand
               reposts of one question are one origin.

NEVER FABRICATED: posted_at, platform_event_ref, author_ref and context_ref
may be null when the export does not have them. Without an event ref the
locator is a deterministic digest of (platform, question, context, author);
genuinely distinct but indistinguishable questions then collapse into one
record -- reported, not hidden.

NOT EVIDENCE OF ANYTHING BUT THE QUESTION: an audience question is
UNVERIFIED and can never be VERIFIED; it shows that someone asked, not that
anything asked about is true, wanted, bought or accepted. Engagement
metrics (views, likes, shares...) are refused inside a question and kept in
a separate engagement ledger, labelled NOT_EVIDENCE, that no other part of
the system reads. A question an operator marks commercial_interest is
treated by R4 as commercial: any cycle using it needs explicit human
approval. Audience records authorize nothing.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from evidence_envelope import envelope
from cognition import commerce, cxp

YOUTUBE, FACEBOOK, LINKEDIN = "YOUTUBE", "FACEBOOK", "LINKEDIN"
PLATFORMS = (YOUTUBE, FACEBOOK, LINKEDIN)
ACQUISITIONS = ("MANUAL_EXPORT", "MANUAL_TRANSCRIPTION", "SYNTHETIC_FIXTURE")
SOURCE_TYPE = "platform_event"
ENGAGEMENT_METRICS = ("views", "likes", "shares", "comments", "reactions", "impressions", "watch_minutes")

ACCEPTED = "ACCEPTED"
DUPLICATE_IMPORT = "DUPLICATE_IMPORT"
REJECTED = "REJECTED"
MAX_RESEARCH_INPUTS = 8

_KEYS = frozenset({"platform", "statement", "platform_event_ref", "context_ref", "author_ref", "posted_at",
                   "reposted_from", "acquisition", "commercial_interest"})
_EVENT_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
_AUTHOR_REF = re.compile(r"^author-[a-z0-9][a-z0-9-]{2,62}$")
_ORIGIN_REF = re.compile(r"^origin-[a-z0-9][a-z0-9-]{2,62}$")
_HANDLE = re.compile(r"(^|[\s(])@[A-Za-z0-9_.]{2,}")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$")


def _refuse(code, detail):
    raise cxp.CXPError(code, detail)


def locator(payload: dict) -> str:
    platform = payload["platform"].lower()
    if payload["platform_event_ref"]:
        return f"{platform}:{payload['platform_event_ref']}"
    basis = {k: payload[k] for k in ("statement", "context_ref", "author_ref")}
    return f"{platform}:unreferenced:{hashlib.sha256(cxp.canonical_bytes(basis)).hexdigest()[:32]}"


def check_payload(payload: dict) -> None:
    engagement = sorted(set(payload) & set(ENGAGEMENT_METRICS))
    if engagement:
        _refuse(cxp.E_MALFORMED, f"engagement metrics {engagement} are not part of an audience question; "
                                 "record them with AudienceIntake.record_engagement()")
    if set(payload) != _KEYS:
        _refuse(cxp.E_MALFORMED, f"AUDIENCE_QUESTION payload requires exactly {sorted(_KEYS)}")
    if payload["platform"] not in PLATFORMS:
        _refuse(cxp.E_MALFORMED, f"platform must be one of {PLATFORMS}")
    if payload["acquisition"] not in ACQUISITIONS:
        _refuse(cxp.E_MALFORMED, f"acquisition must be one of {ACQUISITIONS}; nothing scraped or API-sourced is accepted")
    commerce._check_summary(payload["statement"])  # length, contact and banking details
    if _HANDLE.search(payload["statement"]):
        _refuse(cxp.E_SENSITIVE_DATA, "question text contains an @handle; remove personal identifiers before import")
    for name in ("platform_event_ref", "context_ref", "reposted_from"):
        value = payload[name]
        if value is not None and not (isinstance(value, str) and _EVENT_REF.match(value)):
            _refuse(cxp.E_MALFORMED, f"{name} must be a platform reference or null")
    if payload["author_ref"] is not None and not (isinstance(payload["author_ref"], str) and _AUTHOR_REF.match(payload["author_ref"])):
        _refuse(cxp.E_MALFORMED, "author_ref must be an opaque author-<slug> pseudonym or null, never a name or handle")
    if payload["posted_at"] is not None and not (isinstance(payload["posted_at"], str) and _TIMESTAMP.match(payload["posted_at"])):
        _refuse(cxp.E_MALFORMED, "posted_at must be the platform's ISO-8601 timestamp, or null if the export lacks it")
    if not isinstance(payload["commercial_interest"], bool):
        _refuse(cxp.E_MALFORMED, "commercial_interest must be true or false")
    if payload["reposted_from"] is not None and payload["reposted_from"] == payload["platform_event_ref"]:
        _refuse(cxp.E_MALFORMED, "an event cannot be a repost of itself")


def check_labels(payload: dict, provenance: str, representation: str, verification: str, sources: tuple) -> None:
    if provenance not in (cxp.OBSERVED, cxp.HUMAN_ASSERTED):
        _refuse(cxp.E_KIND_RULE, "AUDIENCE_QUESTION provenance must be OBSERVED or HUMAN_ASSERTED")
    if representation not in (cxp.REP_QUOTATION, cxp.REP_PARAPHRASE):
        _refuse(cxp.E_KIND_RULE, "AUDIENCE_QUESTION representation must be QUOTATION or PARAPHRASE")
    if verification != cxp.VER_UNVERIFIED:
        _refuse(cxp.E_KIND_RULE, "an audience question records that someone asked; it is never verified")
    if len(sources) != 1 or sources[0].source_type != SOURCE_TYPE or sources[0].locator != locator(payload):
        _refuse(cxp.E_KIND_RULE, "AUDIENCE_QUESTION cites exactly one platform_event source matching its platform reference")


def topic_id(question: str) -> str:
    """RESEARCH-TOPIC identity: the question's exact text and nothing else
    (no platform, author, event or time), so identical questions from any
    source map to one topic. Not normalized: changing a character changes
    the topic, as with every CXP identity."""
    return cxp.digest_id("content", {"kind": "AUDIENCE_QUESTION_TOPIC", "question": question})


def audience_metadata(payload: dict) -> dict:
    """Payload-free index for the exchange: refs, flags and the topic digest,
    never the text itself."""
    meta = {k: payload[k] for k in ("platform", "platform_event_ref", "context_ref", "reposted_from", "commercial_interest")}
    meta["topic_id"] = topic_id(payload["statement"])
    return meta


class AudienceIntake:
    def __init__(self, exchange, root: Path):
        self.exchange = exchange
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._engagement = self.root / "engagement.jsonl"
        self._lock_path = self.root / "engagement.lock"

    @property
    def grants_execution_authority(self) -> bool:
        return False

    # -- questions ---------------------------------------------------------------

    def _origin_of_original(self, platform: str, event_ref: str):
        for meta in self.exchange.all_record_metadata():
            a = meta.get("audience")
            if a and a["platform"] == platform and a["platform_event_ref"] == event_ref:
                return meta["sources"][0]["independence_key"]
        return None

    def question_event(self, item: dict, batch_id: str, imported_at: str) -> dict:
        payload = {"platform": item.get("platform"), "statement": item.get("question"),
                   "platform_event_ref": item.get("platform_event_ref"), "context_ref": item.get("context_ref"),
                   "author_ref": item.get("author_ref"), "posted_at": item.get("posted_at"),
                   "reposted_from": item.get("reposted_from"), "acquisition": item.get("acquisition"),
                   "commercial_interest": item.get("commercial_interest", False)}
        payload.update({k: item[k] for k in ENGAGEMENT_METRICS if k in item})  # refused downstream, loudly
        platform = payload["platform"] if payload["platform"] in PLATFORMS else "UNKNOWN"
        origin = item.get("origin_ref")
        if origin is not None and not (isinstance(origin, str) and _ORIGIN_REF.match(origin)):
            raise cxp.CXPError(cxp.E_MALFORMED, "origin_ref must look like origin-<slug>")
        if origin is None and payload["reposted_from"]:
            origin = self._origin_of_original(platform, payload["reposted_from"]) or f"event:{platform}:{payload['reposted_from']}"
        if origin is None and payload["author_ref"]:
            origin = f"author:{platform}:{payload['author_ref']}"
        if origin is None and payload["platform_event_ref"]:
            origin = f"event:{platform}:{payload['platform_event_ref']}"
        source = {"source_type": SOURCE_TYPE,
                  "locator": locator(payload) if platform != "UNKNOWN" and isinstance(payload["statement"], str) else "invalid:invalid"}
        if origin is not None:
            source["independence_key"] = origin
        transcribed = payload["acquisition"] == "MANUAL_TRANSCRIPTION"
        return {
            "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_AUDIENCE_QUESTION,
            "representation": cxp.REP_PARAPHRASE if item.get("paraphrased") else cxp.REP_QUOTATION,
            "evidence": cxp.EV_SINGLE_SOURCE, "verification": cxp.VER_UNVERIFIED,
            "provenance": cxp.HUMAN_ASSERTED if transcribed else cxp.OBSERVED,
            "privacy": item.get("privacy", cxp.PRIV_INTERNAL), "payload": payload, "sources": [source],
            "derived_from": [], "verification_ref": None, "consent_ref": None,
            "occurrence": {"emitter_id": "audience-intake", "observed_at": imported_at, "correlation_id": batch_id,
                           "causation_id": None},
        }

    def import_batch(self, batch_id: str, items, imported_at: str) -> dict:
        """Import one manually supplied batch. Originals are processed before
        reposts so a repost can inherit its original's origin."""
        batch_id = cxp._validate_identifier(batch_id, "batch_id")
        order = sorted(range(len(items)), key=lambda i: (bool(items[i].get("reposted_from")), i))
        results = [None] * len(items)
        for i in order:
            try:
                event = self.question_event(items[i], batch_id, imported_at)
            except cxp.CXPError as exc:
                results[i] = {"index": i, "status": REJECTED, "error_code": exc.code, "detail": exc.detail}
                continue
            receipt = self.exchange.ingest(event)
            if receipt.status == "REJECTED":
                results[i] = {"index": i, "status": REJECTED, "error_code": receipt.error_code, "detail": receipt.detail}
                continue
            meta = self.exchange.record_metadata(receipt.record_id)
            results[i] = {"index": i, "status": ACCEPTED if receipt.status == "ACCEPTED" else DUPLICATE_IMPORT,
                          "record_id": receipt.record_id, "topic_id": meta["audience"]["topic_id"],
                          "origin": meta["sources"][0]["independence_key"], "occurrence_id": receipt.occurrence_id}
        counts = {s: sum(r["status"] == s for r in results) for s in (ACCEPTED, DUPLICATE_IMPORT, REJECTED)}
        return {"batch_id": batch_id, "results": results, "counts": counts,
                "distinct_records": len({r["record_id"] for r in results if r.get("record_id")}),
                "distinct_topics": len({r["topic_id"] for r in results if r.get("topic_id")}),
                "independent_origins": len({r["origin"] for r in results if r.get("origin")}),
                "grants_execution_authority": False}

    # -- engagement metrics (never evidence) ----------------------------------------

    def record_engagement(self, platform: str, content_ref: str, metric: str, value: int, captured_at: str,
                          batch_id: str) -> dict:
        if platform not in PLATFORMS or metric not in ENGAGEMENT_METRICS:
            raise ValueError("unknown platform or metric")
        if not isinstance(content_ref, str) or not _EVENT_REF.match(content_ref):
            raise ValueError("content_ref must be a platform reference")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("value must be a non-negative integer")
        if not isinstance(captured_at, str) or not _TIMESTAMP.match(captured_at):
            raise ValueError("captured_at must be an ISO-8601 timestamp")
        entry = {"platform": platform, "content_ref": content_ref, "metric": metric, "value": value,
                 "captured_at": captured_at, "batch_id": cxp._validate_identifier(batch_id, "batch_id"),
                 "evidence_status": "NOT_EVIDENCE"}
        entry["entry_id"] = hashlib.sha256(cxp.canonical_bytes(entry)).hexdigest()
        with envelope._FileLock(self._lock_path, timeout_seconds=5.0):
            entries = self.engagement()
            if entry["entry_id"] not in {e["entry_id"] for e in entries}:
                envelope._atomic_write_bytes(self._engagement, envelope._serialize_ledger(list(entries) + [entry]))
        return entry

    def engagement(self) -> tuple:
        if not self._engagement.exists():
            return ()
        return tuple(json.loads(line) for line in self._engagement.read_text(encoding="utf-8").splitlines() if line)

    # -- the bounded bridge to R4 -----------------------------------------------------

    def research_cycle(self, runner, question_ids, topic: str, observed_at: str, parent_cycle_id: str = None,
                       approval_id: str = None) -> dict:
        """Offer accepted audience questions to a governed research cycle.
        This only checks that the inputs ARE audience questions; novelty,
        lineage, budget, duplication and the commercial boundary are decided
        by R4 inside the cycle runner, never here."""
        ids = sorted(set(question_ids))
        if not 1 <= len(ids) <= MAX_RESEARCH_INPUTS:
            raise ValueError(f"offer 1-{MAX_RESEARCH_INPUTS} questions per cycle")
        for rid in ids:
            meta = self.exchange.record_metadata(rid)
            if meta is None or meta["kind"] != cxp.KIND_AUDIENCE_QUESTION or meta["erased"]:
                raise ValueError(f"{rid} is not an accepted, unerased audience question")
        return runner.run([], topic, observed_at, parent_cycle_id=parent_cycle_id, approval_id=approval_id,
                          extra_input_ids=ids)
