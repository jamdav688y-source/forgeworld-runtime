"""FW-IMPORT-1: governed, local import of operator-supplied conversations.

Two input formats, both supplied by the operator as files (nothing here
reads LinkedIn, a mailbox or any network):

  LinkedIn data export CSV  (LinkedIn "Get a copy of your data" messages.csv:
                             CONVERSATION ID, FROM, SENDER PROFILE URL, DATE,
                             CONTENT, ...; DATE as "YYYY-MM-DD HH:MM:SS UTC")
  plain-text record         CONVERSATION: <id>
                            ---
                            [2026-10-18T03:23:40Z] <speaker>:
                            message text, kept exactly, until the next
                            [timestamp] line

Every message becomes one ordinary CXP OBSERVATION (QUOTATION, OBSERVED):
  statement     the original message text, byte for byte (too long -> refused,
                never truncated)
  subject       conversation / message / author / original time / source_ref /
                import time
  sources       customer:<customer_ref>/conversation/<cid>/<mid>  (the stable
                message identifier; operator messages use
                operator:<operator-id>/conversation/<cid>/<mid> instead, so they
                are never customer evidence) and import-file:sha256:<hex>, both
                with the author's independence key -- one person is one origin,
                however many files mention them
  occurrence    observed_at = the message's original timestamp
  privacy       INTERNAL: R1 persists nothing more restrictive, so a person's
                words rely on erase() and on never leaving the operator's store
  consent_ref   the engagement's consent record (ENGAGE-1)

Rules, checked for the whole file before anything is written:
  - explicit binding: customer_ref + engagement_ref + a live consent record of
    that engagement (destination.consent_problems); an engagement already bound
    to another customer by an outcome spec is refused
  - explicit identity: every author in the conversation must be mapped by the
    operator (export identity -> customer-author:<slug> | operator:<id>); an
    unmapped author, or one display name with several profile URLs, is
    AMBIGUOUS -- there is no fuzzy matching
  - a conversation already imported for another customer is refused
  - provenance (source_ref) and well-formed timestamps are required
Duplicates are suppressed by message identifier, so re-running an import,
resuming an interrupted one or importing an overlapping later export adds
only messages not yet recorded.

Importing never interprets. classify() records one operator's label for one
message as a separate CLAIM (INFERENCE, DERIVED) from a fixed vocabulary;
nothing here qualifies a prospect, starts a cycle or sends anything.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone

from cognition import bundle, cxp, delivery as dv, destination as ds, episode as ep

CSV_COLUMNS = ("CONVERSATION ID", "FROM", "SENDER PROFILE URL", "DATE", "CONTENT")
LABELS = ("PROBLEM_STATEMENT", "QUESTION", "REQUEST_FOR_PROPOSAL", "SCHEDULING", "COMMITMENT", "OBJECTION", "OTHER")

I_NO_CONSENT = "CONSENT_NOT_ESTABLISHED"
I_AMBIGUOUS = "AMBIGUOUS_IDENTITY"
I_CROSS_CUSTOMER = "CROSS_CUSTOMER_CONTAMINATION"
I_MALFORMED = "MALFORMED_IMPORT"
I_TIMESTAMP = "MALFORMED_TIMESTAMP"
I_PROVENANCE = "MISSING_PROVENANCE"

_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=:-]{0,127}$")
_SOURCE_REF = re.compile(r"^[a-z][a-z0-9-]*:[^\s]{1,200}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_HEADER = re.compile(r"^\[([^\]]+)\] ([^:\n]{1,120}):[ \t]?(.*)$")
_LINKEDIN_DATE = "%Y-%m-%d %H:%M:%S UTC"


class ImportRefused(Exception):
    def __init__(self, reasons):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)


def _iso(value: str) -> str:
    for fmt in (_LINKEDIN_DATE, "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value.strip(), fmt).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, AttributeError):
            continue
    raise ValueError(value)


def parse_linkedin_csv(data: bytes, conversation_id: str) -> list:
    """Rows of one conversation from a LinkedIn messages export, oldest first."""
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or ())]
        if missing:
            raise ImportRefused([f"{I_MALFORMED}: export lacks columns {missing}"])
        rows = [r for r in reader if r["CONVERSATION ID"] == conversation_id]
    except (UnicodeDecodeError, csv.Error):
        raise ImportRefused([f"{I_MALFORMED}: not a UTF-8 CSV export"]) from None
    out = []
    for r in rows:
        try:
            sent_at = _iso(r["DATE"])
        except ValueError:
            raise ImportRefused([f"{I_TIMESTAMP}: {r['DATE']!r}"]) from None
        identity = r["SENDER PROFILE URL"].strip() or f"name:{r['FROM'].strip()}"
        out.append({"identity": identity, "display_name": r["FROM"].strip(), "sent_at": sent_at,
                    "text": r["CONTENT"]})
    return sorted(out, key=lambda m: m["sent_at"])


def parse_text_record(data: bytes) -> tuple:
    """(conversation_id, messages) from the plain-text record format."""
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        raise ImportRefused([f"{I_MALFORMED}: not UTF-8 text"]) from None
    if len(lines) < 3 or not lines[0].startswith("CONVERSATION: ") or lines[1] != "---":
        raise ImportRefused([f"{I_MALFORMED}: expected 'CONVERSATION: <id>' then '---'"])
    conversation_id = lines[0][len("CONVERSATION: "):].strip()
    messages, current = [], None
    for line in lines[2:]:
        match = _HEADER.match(line)
        if match:
            try:
                sent_at = _iso(match.group(1))
            except ValueError:
                raise ImportRefused([f"{I_TIMESTAMP}: {match.group(1)!r}"]) from None
            current = {"identity": f"speaker:{match.group(2).strip()}", "display_name": match.group(2).strip(),
                       "sent_at": sent_at, "lines": [match.group(3)]}
            messages.append(current)
        elif current is None:
            if line.strip():
                raise ImportRefused([f"{I_MALFORMED}: text before the first [timestamp] speaker: line"])
        else:
            current["lines"].append(line)
    for m in messages:
        while len(m["lines"]) > 1 and m["lines"][-1] == "":  # blank separator lines are not content
            m["lines"].pop()
        m["text"] = "\n".join(m.pop("lines"))
    return conversation_id, messages


def message_id(conversation_id: str, author: str, m: dict) -> str:
    """Stable identifier: the content address of who (the operator-mapped
    author, not the export's spelling of them) said what, when -- so the same
    conversation supplied as an export and as a text record is one set of
    messages."""
    return "msg-" + bundle.sha256_hex(cxp.canonical_bytes(
        {"conversation_id": conversation_id, "author": author, "sent_at": m["sent_at"], "text": m["text"]}))[:32]


class ConversationImporter:
    def __init__(self, exchange, governor):
        self.exchange = exchange
        self.governor = governor

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def import_linkedin_csv(self, data: bytes, *, conversation_id: str, **binding) -> dict:
        if not isinstance(conversation_id, str) or not _CONVERSATION_ID.match(conversation_id):
            raise ImportRefused([f"{I_MALFORMED}: conversation_id"])
        return self._import(conversation_id, parse_linkedin_csv(data, conversation_id), data, **binding)

    def import_text(self, data: bytes, **binding) -> dict:
        conversation_id, messages = parse_text_record(data)
        return self._import(conversation_id, messages, data, **binding)

    # -- core -------------------------------------------------------------------------

    def _index(self):
        metas = {m["record_id"]: m for m in self.exchange.all_record_metadata()}
        return metas, {s["locator"]: rid for rid, m in metas.items() if not m["erased"]
                       for s in m.get("root_sources", ())}

    def _import(self, conversation_id, messages, data, *, customer_ref, engagement_ref, consent_record_id,
                participants: dict, source_ref, synthetic, operator_id, imported_at) -> dict:
        if self.governor._active_cycles:
            raise ImportRefused(["IMPORT_DURING_RUNNING_CYCLE"])
        if not isinstance(operator_id, str) or not ep._REVIEWER.match(operator_id):
            raise ImportRefused(["UNAUTHORIZED_IMPORTER: a human operator id (operator-<slug>) is required"])
        problems = []
        if not isinstance(source_ref, str) or not _SOURCE_REF.match(source_ref):
            problems.append(f"{I_PROVENANCE}: source_ref like 'linkedin-export:2026-10-19' is required")
        if not isinstance(conversation_id, str) or not _CONVERSATION_ID.match(conversation_id):
            problems.append(f"{I_MALFORMED}: conversation_id")
        if not isinstance(imported_at, str) or not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", imported_at):
            problems.append(f"{I_TIMESTAMP}: imported_at must be YYYY-MM-DDTHH:MM:SSZ")
        if not messages:
            problems.append(f"{I_MALFORMED}: no messages for this conversation")
        if not isinstance(synthetic, bool) or not isinstance(customer_ref, str) or not dv._CUSTOMER.match(customer_ref) \
                or customer_ref.startswith("customer-synthetic-") != synthetic \
                or not isinstance(engagement_ref, str) or engagement_ref.startswith("eng-synthetic-") != synthetic:
            problems.append(f"{I_MALFORMED}: customer_ref / engagement_ref / synthetic flag disagree")
        metas, locators = self._index()
        if not problems:
            consent = ds.consent_problems(consent_record_id, engagement_ref, metas.get, metas) \
                if isinstance(consent_record_id, str) else ["CONSENT_RECORD_MISSING"]
            problems += [f"{I_NO_CONSENT}: {p}" for p in consent]
            for m in metas.values():
                spec = m.get("outcome_spec")
                if spec and not m["erased"] and spec.get("engagement_ref") == engagement_ref \
                        and spec["customer_ref"] != customer_ref:
                    problems.append(f"{I_CROSS_CUSTOMER}: engagement {engagement_ref} serves another customer")
                    break
            needle = f"/conversation/{conversation_id}/"
            if any(loc.startswith("customer:") and needle in loc and not loc.startswith(f"customer:{customer_ref}/")
                   for loc in locators):
                problems.append(f"{I_CROSS_CUSTOMER}: conversation {conversation_id} belongs to another customer")
        # identity: every author mapped explicitly; one display name may not hide two identities
        authors = {}
        for m in messages:
            target = participants.get(m["identity"]) if isinstance(participants, dict) else None
            if target is None:
                problems.append(f"{I_AMBIGUOUS}: unmapped author {m['identity']!r}")
                continue
            kind, _, who = target.partition(":")
            if not ((kind == "customer-author" and _SLUG.match(who)) or (kind == "operator" and ep._REVIEWER.match(who))):
                problems.append(f"{I_AMBIGUOUS}: mapping for {m['identity']!r} must be customer-author:<slug> or "
                                f"operator:<operator-id>")
            authors.setdefault(m["display_name"], set()).add(m["identity"])
            if len(m["text"]) > cxp.MAX_STATEMENT_CHARS or not m["text"].strip():
                problems.append(f"{I_MALFORMED}: message at {m['sent_at']} is empty or longer than "
                                f"{cxp.MAX_STATEMENT_CHARS} characters (content is never truncated)")
        problems += [f"{I_AMBIGUOUS}: display name {name!r} maps to {len(ids)} identities"
                     for name, ids in sorted(authors.items()) if len(ids) > 1]
        if problems:
            raise ImportRefused(sorted(set(problems)))

        file_locator = f"import-file:sha256:{bundle.sha256_hex(data)}"
        source_type = "synthetic_fixture" if synthetic else "document"
        results = []
        for m in messages:
            mid = message_id(conversation_id, participants[m["identity"]], m)
            kind, _, who = participants[m["identity"]].partition(":")
            owner = f"customer:{customer_ref}" if kind == "customer-author" else f"operator:{who}"
            locator = f"{owner}/conversation/{conversation_id}/{mid}"
            if locator in locators:
                results.append({"message_id": mid, "status": "DUPLICATE_SUPPRESSED", "record_id": locators[locator]})
                continue
            key = f"{owner}/author/{who}"
            receipt = self.exchange.ingest({
                "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_OBSERVATION,
                "representation": cxp.REP_QUOTATION, "evidence": cxp.EV_SINGLE_SOURCE,
                "verification": cxp.VER_UNVERIFIED, "provenance": cxp.OBSERVED, "privacy": cxp.PRIV_INTERNAL,
                "payload": {"statement": m["text"],
                            "subject": f"conversation:{conversation_id} message:{mid} author:{kind}:{who} "
                                       f"sent_at:{m['sent_at']} source:{source_ref} imported_at:{imported_at}"},
                "sources": [{"source_type": source_type, "locator": locator, "independence_key": key},
                            {"source_type": source_type, "locator": file_locator, "independence_key": key}],
                "derived_from": [], "verification_ref": None, "consent_ref": consent_record_id,
                "occurrence": {"emitter_id": operator_id, "observed_at": m["sent_at"], "correlation_id": None,
                               "causation_id": None}})
            if receipt.status == "REJECTED":
                raise ImportRefused([f"{receipt.error_code}: {receipt.detail}"]
                                    + [f"imported before refusal: {r['message_id']}" for r in results])
            results.append({"message_id": mid, "status": "IMPORTED", "record_id": receipt.record_id})
            locators[locator] = receipt.record_id
        return {"conversation_id": conversation_id, "customer_ref": customer_ref, "engagement_ref": engagement_ref,
                "source_ref": source_ref, "file_sha256": file_locator.rsplit(":", 1)[1], "messages": results,
                "counts": {s: sum(r["status"] == s for r in results) for s in ("IMPORTED", "DUPLICATE_SUPPRESSED")},
                "classified": False, "grants_execution_authority": False}

    # -- separate, human interpretation -----------------------------------------------

    def classify(self, message_record_id: str, label: str, operator_id: str, observed_at: str) -> str:
        """One operator's label for one imported message, recorded as a CLAIM
        derived from it. Never automatic; never changes the message."""
        if not isinstance(operator_id, str) or not ep._REVIEWER.match(operator_id):
            raise ImportRefused(["UNAUTHORIZED_CLASSIFIER: a human operator id (operator-<slug>) is required"])
        if label not in LABELS:
            raise ImportRefused([f"UNKNOWN_LABEL: one of {LABELS}"])
        meta = self.exchange.record_metadata(message_record_id)
        if meta is None or meta["kind"] != cxp.KIND_OBSERVATION or not any(
                "/conversation/" in s["locator"] for s in meta["root_sources"]):
            raise ImportRefused(["NOT_AN_IMPORTED_MESSAGE"])
        receipt = self.exchange.ingest({
            "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_CLAIM, "representation": cxp.REP_INFERENCE,
            "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED, "provenance": cxp.DERIVED,
            "privacy": meta["privacy"],
            "payload": {"statement": f"OPERATOR CLASSIFICATION: {label}", "subject": f"classified-by:{operator_id}"},
            "sources": [], "derived_from": [message_record_id], "verification_ref": None,
            "consent_ref": meta.get("consent_ref"),
            "occurrence": {"emitter_id": operator_id, "observed_at": observed_at, "correlation_id": None,
                           "causation_id": None}})
        if receipt.status == "REJECTED":
            raise ImportRefused([f"{receipt.error_code}: {receipt.detail}"])
        return receipt.record_id
