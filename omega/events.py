"""Canonical event model, schema fw.omega.event/1 (Stage B).

An event is a signed HEADER plus a separately hashed PAYLOAD:

    header = {
      schema          "fw.omega.event/1"
      event_type      a key of policy.EVENT_TYPES
      device_id       the device that wrote it (owner of the signing key)
      actor_id        who caused it ("human:<name>", "model:<name>", ...)
      actor_kind      HUMAN | MODEL | TOOL | SYSTEM
      seq             per-device monotonic integer, starting at 1
      prev            event_id of this device's seq-1 event (hash chain) or null
      ts              claimed UTC time "YYYY-MM-DDTHH:MM:SSZ" (informational;
                      causality comes from prev / parents, never from clocks)
      parents         sorted event_ids this event causally follows (other devices
                      included); the reconciler relies on these, not on ts
      payload_hash    sha256 domain "payload" over the canonical payload
      artifacts       sorted sha256 hex of original source artifacts
      provenance      list of {"kind": source|derived_from|tool|import, "ref": str}
      links           sorted entity ids ("contact:ct_...", "deal:...", "task:...")
      privacy         PUBLIC | INTERNAL | PRIVATE | SECRET | DEVICE_LOCAL
      scope           authorization scope (policy.SCOPES), fixed per event type
      verification    UNVERIFIED | VERIFIED | CONTESTED | REFUTED (as asserted)
      supersedes      event_id or null (a newer statement of the same thing)
      corrects        event_id or null (a correction; history is never rewritten)
    }
    event_id  = "ev_" + sha256(domain "event", header)
    signature = Ed25519(device key, event_id ascii)

Because the payload is bound only by its hash, a payload can be WITHHELD
(peer not cleared for its privacy class) or PURGED (authorized deletion)
while the header stays verifiable and the per-device chain stays intact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from omega import SCHEMA, policy
from omega.canonical import CanonicalError, canonical, digest

EVENT_ID_RE = re.compile(r"^ev_[0-9a-f]{64}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DEVICE_RE = re.compile(r"^dev_[0-9a-f]{32}$")
PROVENANCE_KINDS = ("source", "derived_from", "tool", "import")
MAX_TEXT = 20000


class EventError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def payload_hash(payload: dict) -> str:
    return digest("payload", payload)


def event_id_for(header: dict) -> str:
    return "ev_" + digest("event", header)


@dataclass(frozen=True)
class Event:
    header: dict
    signature: str
    payload: Optional[dict]          # None when withheld / purged

    @property
    def event_id(self) -> str:
        return event_id_for(self.header)

    def __getattr__(self, name):
        h = object.__getattribute__(self, "header")
        if name in h:
            return h[name]
        raise AttributeError(name)

    def envelope(self, include_payload: bool = True) -> dict:
        return {"header": self.header, "signature": self.signature,
                "payload": self.payload if include_payload else None}


# ---------------------------------------------------------------------------
# payload validation (strict, per type)
# ---------------------------------------------------------------------------
def _s(p, k, required=True, max_len=MAX_TEXT):
    v = p.get(k)
    if v is None and not required:
        return
    if not isinstance(v, str) or not v.strip() or len(v) > max_len:
        raise EventError("PAYLOAD_INVALID", f"{k} must be a non-empty string <= {max_len}")


def _enum(p, k, allowed):
    if p.get(k) not in allowed:
        raise EventError("PAYLOAD_INVALID", f"{k} must be one of {allowed}")


def _int(p, k, required=True, minimum=0):
    v = p.get(k)
    if v is None and not required:
        return
    if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
        raise EventError("PAYLOAD_INVALID", f"{k} must be an integer >= {minimum}")


def _strlist(p, k):
    v = p.get(k, [])
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise EventError("PAYLOAD_INVALID", f"{k} must be a list of strings")


def _ev(p, k, required=True):
    v = p.get(k)
    if v is None and not required:
        return
    if not isinstance(v, str) or not EVENT_ID_RE.match(v):
        raise EventError("PAYLOAD_INVALID", f"{k} must be an event id")


def _date(p, k, required=True):
    v = p.get(k)
    if v is None and not required:
        return
    if not isinstance(v, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        raise EventError("PAYLOAD_INVALID", f"{k} must be YYYY-MM-DD")


def _check_payload(etype: str, p: dict, header: dict):
    if etype == "ARTIFACT_INGESTED":
        if not SHA_RE.match(str(p.get("sha256", ""))):
            raise EventError("PAYLOAD_INVALID", "sha256")
        _s(p, "media_type"); _s(p, "locator"); _int(p, "size")
        if p["sha256"] not in header["artifacts"]:
            raise EventError("PROVENANCE_MISSING", "artifact must be listed in header.artifacts")
    elif etype == "NOTE_RECORDED":
        _s(p, "text")
    elif etype == "PROJECT_ASSERTED":
        _s(p, "project_id"); _s(p, "name")
    elif etype == "CONTACT_ASSERTED":
        _s(p, "contact_id"); _s(p, "display_name", required=False)
        _strlist(p, "aliases"); _strlist(p, "boundaries")
        ch = p.get("channels", [])
        if not isinstance(ch, list) or not all(isinstance(c, dict) and isinstance(c.get("kind"), str)
                                               and isinstance(c.get("address"), str) for c in ch):
            raise EventError("PAYLOAD_INVALID", "channels")
    elif etype == "MESSAGE_RECORDED":
        _s(p, "contact_id"); _s(p, "conversation_id"); _s(p, "channel"); _s(p, "text")
        _enum(p, "direction", ("IN", "OUT"))
        if not TS_RE.match(str(p.get("sent_at", ""))):
            raise EventError("PAYLOAD_INVALID", "sent_at")
        if not any(pr["kind"] == "source" for pr in header["provenance"]):
            raise EventError("PROVENANCE_MISSING", "a message must cite its source")
    elif etype == "FACT_ASSERTED":
        _s(p, "subject"); _s(p, "attribute", max_len=200); _s(p, "value", max_len=2000)
        _enum(p, "basis", ("STATED", "STATED_IN_REPLY", "OPERATOR", "INFERRED"))
        _ev(p, "source_event", required=p.get("basis") != "OPERATOR")
        if p["basis"] == "INFERRED" and header["verification"] != "UNVERIFIED":
            raise EventError("PAYLOAD_INVALID", "an inferred fact cannot be asserted verified")
    elif etype == "COMMITMENT_RECORDED":
        _s(p, "commitment_id"); _s(p, "contact_id"); _s(p, "text")
        _enum(p, "owed_by", ("US", "THEM")); _date(p, "due", required=False)
    elif etype == "COMMITMENT_STATUS":
        _s(p, "commitment_id"); _enum(p, "status", ("OPEN", "DONE", "CANCELLED"))
    elif etype == "DRAFT_PRODUCED":
        _s(p, "contact_id"); _s(p, "text"); _s(p, "generator")
        if not isinstance(p.get("findings"), list):
            raise EventError("PAYLOAD_INVALID", "findings")
    elif etype == "COMMERCE_SIGNAL":
        _s(p, "deal_id"); _enum(p, "stage", policy.COMMERCE_STAGES); _s(p, "summary", max_len=2000)
        _int(p, "amount_minor", required=False); _s(p, "currency", required=False, max_len=3)
        _s(p, "reference", required=False, max_len=200); _date(p, "due", required=False)
        st = p["stage"]
        if st not in policy.COMMERCE_TOOL_STAGES and header["actor_kind"] != "HUMAN":
            raise EventError("ACTOR_NOT_PERMITTED", f"stage {st} requires a human assertion")
        if st == "WRITTEN_AGREEMENT" and not header["artifacts"]:
            raise EventError("PROVENANCE_MISSING", "a written agreement needs the signed document artifact")
        if st == "DELIVERABLE_ACCEPTED" and not any(
                pr["kind"] == "source" and pr["ref"].startswith(("customer:", "message:", "ev_"))
                for pr in header["provenance"]):
            raise EventError("PROVENANCE_MISSING", "acceptance must cite a customer-originated source")
        if st in ("INVOICE_ISSUED", "PAYMENT_ATTEMPTED", "PAYMENT_CLAIMED"):
            _int(p, "amount_minor"); _s(p, "currency", max_len=3); _s(p, "reference", max_len=200)
    elif etype == "PAYMENT_VERIFIED":
        _s(p, "deal_id"); _s(p, "reference", max_len=200); _int(p, "amount_minor"); _s(p, "currency", max_len=3)
        _enum(p, "settlement_source", policy.SETTLEMENT_SOURCES)
        if not header["artifacts"]:
            raise EventError("PROVENANCE_MISSING", "settlement verification needs a settlement record artifact")
    elif etype == "TASK_QUEUED":
        _s(p, "task_id"); _s(p, "action", max_len=100)
        if not isinstance(p.get("args"), dict) or not isinstance(p.get("external_effect"), bool):
            raise EventError("PAYLOAD_INVALID", "args / external_effect")
        if p.get("target_device") is not None and not DEVICE_RE.match(p["target_device"]):
            raise EventError("PAYLOAD_INVALID", "target_device")
    elif etype == "TASK_AUTHORIZED":
        _s(p, "task_id"); _ev(p, "task_event")
        if p.get("authorized_device") != header["device_id"]:
            raise EventError("AUTHORIZATION_NOT_LOCAL",
                             "a task can only be authorized on the device that will execute it")
    elif etype == "TASK_RESULT":
        _s(p, "task_id"); _enum(p, "status", ("SUCCEEDED", "FAILED", "REFUSED")); _s(p, "summary", max_len=4000)
    elif etype == "PEER_PAIRED":
        if not DEVICE_RE.match(str(p.get("peer_device_id", ""))):
            raise EventError("PAYLOAD_INVALID", "peer_device_id")
        _enum(p, "max_privacy", policy.PRIVACY_ORDER)
    elif etype == "ACCESS_REVOKED":
        if not DEVICE_RE.match(str(p.get("peer_device_id", ""))):
            raise EventError("PAYLOAD_INVALID", "peer_device_id")
    elif etype == "DELETION_AUTHORIZED":
        _ev(p, "target_event"); _s(p, "reason")
    elif etype == "RETENTION_POLICY":
        _s(p, "event_type"); _int(p, "max_age_days", minimum=1)
    elif etype == "CONFLICT_RESOLVED":
        _s(p, "key"); _s(p, "value", max_len=2000)
        if not isinstance(p.get("resolved_heads"), list) or not p["resolved_heads"]:
            raise EventError("PAYLOAD_INVALID", "resolved_heads")
        for h in p["resolved_heads"]:
            if not EVENT_ID_RE.match(str(h)):
                raise EventError("PAYLOAD_INVALID", "resolved_heads")
    elif etype == "BENCHMARK_RESULT":
        _s(p, "model"); _s(p, "task_class"); _s(p, "suite_digest")
        _int(p, "score_permille"); _int(p, "latency_ms"); _s(p, "hardware_class")
    elif etype == "AGENT_OPINION":
        _s(p, "role"); _s(p, "subject"); _s(p, "opinion")
    elif etype == "EXPERIMENT_RECORDED":
        _s(p, "experiment_id"); _s(p, "hypothesis"); _s(p, "metric")
        _enum(p, "phase", ("PROPOSED", "MEASURED"))
    elif etype == "PROMOTION_DECISION":
        _s(p, "experiment_id"); _enum(p, "decision", ("PROMOTE", "REJECT", "ROLLBACK"))
        _s(p, "rollback_point"); _ev(p, "gate_event")


def validate(header: dict, payload: Optional[dict]) -> None:
    """Structural + governance validation of a header (and payload if present).
    Raises EventError with a stable code."""
    req = ("schema", "event_type", "device_id", "actor_id", "actor_kind", "seq", "prev", "ts",
           "parents", "payload_hash", "artifacts", "provenance", "links", "privacy", "scope",
           "verification", "supersedes", "corrects")
    if not isinstance(header, dict) or set(header) != set(req):
        raise EventError("SCHEMA_INVALID", f"header fields must be exactly {sorted(req)}")
    if header["schema"] != SCHEMA:
        raise EventError("SCHEMA_UNSUPPORTED", str(header["schema"]))
    et = header["event_type"]
    if et not in policy.EVENT_TYPES:
        raise EventError("EVENT_TYPE_UNKNOWN", str(et))
    allowed_actors, scope = policy.EVENT_TYPES[et]
    if not DEVICE_RE.match(str(header["device_id"])):
        raise EventError("SCHEMA_INVALID", "device_id")
    if header["actor_kind"] not in policy.ACTOR_KINDS:
        raise EventError("SCHEMA_INVALID", "actor_kind")
    if not isinstance(header["actor_id"], str) or not header["actor_id"].startswith(
            header["actor_kind"].lower() + ":"):
        raise EventError("SCHEMA_INVALID", "actor_id must be '<actor_kind>:<name>'")
    if header["actor_kind"] not in allowed_actors:
        raise EventError("ACTOR_NOT_PERMITTED", f"{header['actor_kind']} may not write {et}")
    if header["scope"] != scope:
        raise EventError("SCOPE_MISMATCH", f"{et} belongs to scope {scope}")
    if scope == "governance" and header["actor_kind"] != "HUMAN":
        raise EventError("ACTOR_NOT_PERMITTED", "governance is human-only")
    if not isinstance(header["seq"], int) or isinstance(header["seq"], bool) or header["seq"] < 1:
        raise EventError("SCHEMA_INVALID", "seq")
    if header["seq"] == 1 and header["prev"] is not None:
        raise EventError("CHAIN_INVALID", "seq 1 has no prev")
    if header["seq"] > 1 and not EVENT_ID_RE.match(str(header["prev"])):
        raise EventError("CHAIN_INVALID", "prev required after seq 1")
    if not TS_RE.match(str(header["ts"])):
        raise EventError("SCHEMA_INVALID", "ts")
    for k in ("parents",):
        v = header[k]
        if not isinstance(v, list) or v != sorted(set(v)) or not all(EVENT_ID_RE.match(str(x)) for x in v):
            raise EventError("SCHEMA_INVALID", f"{k} must be a sorted unique list of event ids")
    if not isinstance(header["artifacts"], list) or header["artifacts"] != sorted(set(header["artifacts"])) \
            or not all(SHA_RE.match(str(x)) for x in header["artifacts"]):
        raise EventError("SCHEMA_INVALID", "artifacts")
    if not isinstance(header["links"], list) or header["links"] != sorted(set(header["links"])) \
            or not all(isinstance(x, str) and ":" in x for x in header["links"]):
        raise EventError("SCHEMA_INVALID", "links")
    prov = header["provenance"]
    if not isinstance(prov, list) or not all(isinstance(p, dict) and set(p) == {"kind", "ref"}
                                             and p["kind"] in PROVENANCE_KINDS and isinstance(p["ref"], str)
                                             and p["ref"] for p in prov):
        raise EventError("SCHEMA_INVALID", "provenance")
    if header["privacy"] not in policy.PRIVACY_CLASSES:
        raise EventError("SCHEMA_INVALID", "privacy")
    if header["verification"] not in policy.VERIFICATION_STATES:
        raise EventError("SCHEMA_INVALID", "verification")
    if header["actor_kind"] != "HUMAN" and header["verification"] != policy.NON_HUMAN_MAX_VERIFICATION:
        raise EventError("ACTOR_NOT_PERMITTED", "only a human may assert a verification state")
    for k in ("supersedes", "corrects"):
        if header[k] is not None and not EVENT_ID_RE.match(str(header[k])):
            raise EventError("SCHEMA_INVALID", k)
    if et in ("PEER_PAIRED", "ACCESS_REVOKED") and header["privacy"] != policy.DEVICE_LOCAL:
        raise EventError("SCHEMA_INVALID", f"{et} is device-local")
    if not isinstance(header["payload_hash"], str) or not SHA_RE.match(header["payload_hash"]):
        raise EventError("SCHEMA_INVALID", "payload_hash")
    if payload is not None:
        if not isinstance(payload, dict):
            raise EventError("PAYLOAD_INVALID", "payload must be an object")
        try:
            if payload_hash(payload) != header["payload_hash"]:
                raise EventError("PAYLOAD_HASH_MISMATCH", "payload does not match header.payload_hash")
        except CanonicalError as exc:
            raise EventError("PAYLOAD_INVALID", str(exc))
        _check_payload(et, payload, header)


def build_header(*, event_type, device_id, actor_id, actor_kind, seq, prev, ts, payload,
                 parents=(), artifacts=(), provenance=(), links=(), privacy="PRIVATE",
                 verification="UNVERIFIED", supersedes=None, corrects=None) -> dict:
    return {
        "schema": SCHEMA,
        "event_type": event_type,
        "device_id": device_id,
        "actor_id": actor_id,
        "actor_kind": actor_kind,
        "seq": seq,
        "prev": prev,
        "ts": ts,
        "parents": sorted(set(parents)),
        "payload_hash": payload_hash(payload),
        "artifacts": sorted(set(artifacts)),
        "provenance": [dict(kind=p["kind"], ref=p["ref"]) for p in provenance],
        "links": sorted(set(links)),
        "privacy": privacy,
        "scope": policy.EVENT_TYPES[event_type][1] if event_type in policy.EVENT_TYPES else "memory",
        "verification": verification,
        "supersedes": supersedes,
        "corrects": corrects,
    }


def from_envelope(env: dict) -> Event:
    if not isinstance(env, dict) or set(env) != {"header", "signature", "payload"}:
        raise EventError("SCHEMA_INVALID", "envelope must have exactly header, signature, payload")
    if not isinstance(env["signature"], str):
        raise EventError("SCHEMA_INVALID", "signature")
    try:
        canonical(env["header"])
    except CanonicalError as exc:
        raise EventError("SCHEMA_INVALID", str(exc))
    return Event(header=env["header"], signature=env["signature"], payload=env["payload"])
