"""Universal relationship memory (Stage F).

Contact-specific, provenance-linked memory built only from events. Every
returned fact carries the event ids it rests on.

PRIVACY ISOLATION: everything here is scoped by the contact's entity link
("contact:<id>"). context() for contact A never reads events linked only to
contact B, and check_draft() blocks a draft that carries B's private facts
or identity into A's conversation.

Deterministic, offline: question classification, answer extraction,
novelty detection and drafting are rule based (no model needed). An
optional generator (e.g. forge.OllamaClient) may propose wording; its draft
is accepted only if it passes the same checks, otherwise the deterministic
draft is used and the rejection is recorded.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Callable, Optional

from omega import reconcile
from omega.canonical import digest
from omega.events import event_id_for

TOOL_ACTOR = "tool:omega-relationship"

# attribute -> regexes that identify a QUESTION about it
QUESTION_RULES = {
    "budget": [r"\bbudget\b", r"\bbudget range\b", r"\bhow much (?:are you|do you|can you|would you)\b", r"\bprice range\b",
               r"\bwilling to (?:spend|pay|invest)\b"],
    "timeline": [r"\btimeline\b", r"\bdeadline\b", r"\bwhen do you need\b", r"\bby when\b",
                 r"\bwhen (?:would|do) you (?:want|like|hope) to (?:start|launch|finish)\b"],
    "company": [r"\bwhat company\b", r"\bwhich company\b", r"\bcompany are you\b", r"\bwho do you work (?:for|with)\b",
                r"\bwhere do you work\b", r"\bname of your (?:company|business|organi[sz]ation)\b"],
    "role": [r"\bwhat(?:'s| is) your (?:role|position|title)\b", r"\byour role\b", r"\bwhat do you do at\b"],
    "location": [r"\bwhere are you (?:based|located)\b", r"\bwhat city\b", r"\bwhich city\b",
                 r"\bwhat time ?zone\b"],
    "email": [r"\b(?:your|best) email\b", r"\bemail address\b"],
    "phone": [r"\bphone number\b", r"\bbest number\b"],
    "availability": [r"\bwhen are you (?:free|available)\b", r"\bgood time (?:for|to)\b",
                     r"\bwhat times? work", r"\bavailability\b"],
    "preferred_name": [r"\bwhat should i call you\b", r"\bprefer to be called\b", r"\bhow do you pronounce\b"],
    "goal": [r"\bwhat are you (?:hoping|trying|looking) (?:to|for)\b", r"\bwhat(?:'s| is) your (?:main )?goal\b",
             r"\bwhat would success look like\b", r"\bsuccessful outcome\b", r"\bwhat problem\b"],
}

QUESTION_TEMPLATES = {
    "goal": "What would a successful outcome look like for you?",
    "timeline": "What timeline are you working towards?",
    "budget": "Do you have a budget range in mind?",
    "company": "Which company are you working with on this?",
    "role": "What is your role there?",
    "availability": "When would be a good time for a short call?",
    "location": "Where are you based, so I can suggest sensible meeting times?",
}

INTENT_PLANS = {
    "discovery": ["goal", "timeline", "budget", "company", "role"],
    "proposal": ["goal", "timeline", "budget", "availability"],
    "follow_up": [],
}

MONEY_RE = re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?\s?[kKmM]?\b|\b\d[\d,]*(?:\.\d+)?\s?(?:[kK]\b|usd\b|USD\b|dollars\b|eur\b|EUR\b|gbp\b|GBP\b))")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d\b")
GREETING_RE = re.compile(r"^\s*(?:hi|hello|hey|dear|good (?:morning|afternoon|evening))[\s,]+([A-Z][A-Za-z'\-]+)",
                         re.IGNORECASE)
BOUNDARY_RE = re.compile(r"\b(?:please\s+)?(?:don'?t|do not|never)\s+(call|phone|text|sms|email|message|contact)\s+me\b"
                         r"([^.?!\n]*)", re.IGNORECASE)
BOUNDARY_TERMS = {"call": [r"\bcall\b", r"\bphone\b", r"\bring you\b"], "phone": [r"\bcall\b", r"\bphone\b"],
                  "text": [r"\btext\b", r"\bsms\b"], "sms": [r"\btext\b", r"\bsms\b"], "email": [r"\bemail\b"]}
WEEKEND_TERMS = [r"\bsaturday\b", r"\bsunday\b", r"\bweekend\b"]
STOP = set("a an the to of and or for in on at is are be you your i me my we our it this that with do does can "
           "could would will what which when where who how have has any some there please just".split())


def contact_id_for(primary: str, identity=None) -> str:
    """Keyed by the device secret when an identity is given (the normal path):
    a peer that sees a header link cannot recompute it from a phone number.
    The unkeyed form exists only for callers without a node."""
    norm = primary.strip().lower()
    if identity is not None:
        return "ct_" + identity.secret_tag("contact-id", norm)[:24]
    return "ct_" + digest("contact", norm)[:24]


def entity(contact_id: str) -> str:
    return f"contact:{contact_id}"


def normalize(text: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in text).split())


def tokens(text: str) -> set:
    return {t for t in normalize(text).split() if t not in STOP and len(t) > 1}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def shingles(text: str, k: int = 3) -> set:
    w = normalize(text).split()
    return {" ".join(w[i:i + k]) for i in range(max(1, len(w) - k + 1))} if w else set()


def questions_in(text: str) -> list:
    return [q.strip() for q in re.findall(r"[^.?!\n]*\?", text) if q.strip(" ?")]


def classify_question(q: str) -> Optional[str]:
    low = q.lower()
    for attr, pats in QUESTION_RULES.items():
        if any(re.search(p, low) for p in pats):
            return attr
    return None


def money_value(s: str) -> Optional[int]:
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s?([kKmM])?", s)
    if not m:
        return None
    n = float(m.group(1).replace(",", ""))
    mult = {"k": 1000, "m": 1_000_000}.get((m.group(2) or "").lower(), 1)
    return int(round(n * mult))


def extract_answer(attr: str, text: str) -> Optional[str]:
    if attr == "budget":
        m = MONEY_RE.search(text)
        return m.group(0).strip() if m else None
    if attr == "email":
        m = EMAIL_RE.search(text)
        return m.group(0) if m else None
    if attr == "phone":
        m = PHONE_RE.search(text)
        return m.group(0).strip() if m else None
    if attr == "timeline":
        m = re.search(r"\b(?:by|before|within|in|end of)\s+(?:the\s+)?(?:\d+\s+(?:days?|weeks?|months?)|"
                      r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*(?:\s+\d{1,2})?|q[1-4]|"
                      r"\d{4}-\d{2}-\d{2}|next\s+\w+|this\s+\w+)", text, re.IGNORECASE)
        return m.group(0) if m else None
    if attr == "preferred_name":
        m = re.search(r"\b(?:call me|prefer(?:red)? to be called|goes? by)\s+([A-Z][a-z]+)", text)
        return m.group(1) if m else None
    if attr == "company":
        m = re.search(r"\b(?:i work (?:at|for)|i'?m with|we are|our company is|company is)\s+([A-Z][\w&\-]*(?:\s+[A-Z][\w&\-]*)*)", text)
        return m.group(1) if m else None
    return None


def first_sentence(text: str, limit: int = 300) -> str:
    s = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    return s[:limit]


class RelationshipMemory:
    def __init__(self, node):
        self.node = node

    # ---------------------------------------------------------- recording
    def add_contact(self, display_name: str, *, primary: str, actor: str, aliases=(), channels=(),
                    boundaries=(), privacy: str = "PRIVATE", source: str = "operator:entry") -> str:
        cid = self.find_contact(primary) or contact_id_for(primary, self.node.identity)
        key = f"contact|{cid}|display_name"
        self.node.append("CONTACT_ASSERTED",
                         {"contact_id": cid, "display_name": display_name, "aliases": sorted(set(aliases)),
                          "primary": primary.strip().lower(),
                          "channels": [dict(c) for c in channels], "boundaries": list(boundaries)},
                         actor=actor, links=[entity(cid)], privacy=privacy,
                         provenance=[{"kind": "source", "ref": source}],
                         parents=reconcile.current_heads(self.node, key))
        return cid

    def find_contact(self, primary: str) -> Optional[str]:
        """An existing contact (created here or synced) with this primary channel."""
        norm = primary.strip().lower()
        for e in self.node.events("CONTACT_ASSERTED"):
            if e.payload and e.payload.get("primary") == norm:
                return e.payload["contact_id"]
        return None

    def _message_events(self, cid: str) -> list:
        return [e for e in self.node.events("MESSAGE_RECORDED", entity(cid)) if e.payload is not None]

    def novelty(self, cid: str, text: str) -> dict:
        """Deterministic novelty: EXACT_DUPLICATE (same normalized text),
        NEAR_DUPLICATE (3-gram Jaccard >= 0.8) or NOVEL, against this contact only."""
        norm, sh = normalize(text), shingles(text)
        best, best_id = 0.0, None
        for e in self._message_events(cid):
            if normalize(e.payload["text"]) == norm:
                return {"class": "EXACT_DUPLICATE", "similar_to": event_id_for(e.header), "score_permille": 1000}
            s = jaccard(sh, shingles(e.payload["text"]))
            if s > best:
                best, best_id = s, event_id_for(e.header)
        cls = "NEAR_DUPLICATE" if best >= 0.8 else "NOVEL"
        return {"class": cls, "similar_to": best_id if cls != "NOVEL" else None, "score_permille": int(best * 1000)}

    def record_message(self, cid: str, *, direction: str, text: str, sent_at: str, source_ref: str,
                       actor: str, channel: str = "sms", conversation_id: Optional[str] = None,
                       raw: Optional[bytes] = None, raw_media_type: str = "text/plain",
                       privacy: str = "PRIVATE") -> dict:
        """Record one message with its source. Idempotent on
        (contact, conversation, direction, sent_at, text). If `raw` is given the
        original artifact is stored separately and linked."""
        conversation_id = conversation_id or f"{channel}:{cid}"
        mkey = "mk_" + digest("message", [cid, conversation_id, direction, sent_at, text])[:32]
        for e in self._message_events(cid):
            if e.payload.get("message_key") == mkey:
                return {"event": e, "status": "DUPLICATE", "novelty": {"class": "EXACT_DUPLICATE",
                                                                         "similar_to": event_id_for(e.header)}}
        nov = self.novelty(cid, text)
        payload = {"contact_id": cid, "conversation_id": conversation_id, "channel": channel,
                   "direction": direction, "text": text, "sent_at": sent_at, "message_key": mkey,
                   "novelty": nov["class"]}
        prior = self._message_events(cid)
        parents = [event_id_for(prior[-1].header)] if prior else []
        ev = self.node.append("MESSAGE_RECORDED", payload, actor=actor, links=[entity(cid)], privacy=privacy,
                              provenance=[{"kind": "source", "ref": source_ref}], parents=parents,
                              artifact_data=[(raw, raw_media_type)] if raw is not None else None)
        facts = self._extract_facts(cid, ev) if direction == "IN" else []
        return {"event": ev, "status": "RECORDED", "novelty": nov, "facts": facts}

    def assert_fact(self, cid: str, attribute: str, value: str, *, basis: str, actor: str,
                    source_event: Optional[str] = None, privacy: str = "PRIVATE", corrects: Optional[str] = None):
        key = f"fact|{entity(cid)}|{attribute}"
        cur = reconcile.resolve(self.node, key)
        if cur["status"] == "RESOLVED" and cur["value"] == value and corrects is None:
            return None  # nothing new; never duplicate a known fact
        payload = {"subject": entity(cid), "attribute": attribute, "value": value, "basis": basis}
        if source_event:
            payload["source_event"] = source_event
        prov = [{"kind": "derived_from", "ref": source_event}] if source_event else \
               [{"kind": "source", "ref": "operator:entry"}]
        return self.node.append("FACT_ASSERTED", payload, actor=actor, links=[entity(cid)], privacy=privacy,
                                provenance=prov, parents=cur["heads"] + ([source_event] if source_event else []),
                                corrects=corrects)

    def _extract_facts(self, cid: str, msg_ev) -> list:
        text, mid = msg_ev.payload["text"], event_id_for(msg_ev.header)
        out = []
        for attr in ("email", "phone", "preferred_name", "company"):
            v = extract_answer(attr, text)
            if v:
                out.append((attr, v, "STATED"))
        for m in BOUNDARY_RE.finditer(text):
            verb = m.group(1).lower()
            out.append((f"boundary:{verb}", m.group(0).strip(), "STATED"))
        if re.search(r"\b(?:not|never|don'?t)\b[^.?!]*\b(?:weekends?|saturdays?|sundays?)\b", text, re.IGNORECASE):
            out.append(("boundary:weekend", first_sentence(text), "STATED"))
        # answers to our previous question(s) in this conversation
        prev_out = self._last_outgoing_before(cid, msg_ev)
        if prev_out is not None:
            asked = [(q, classify_question(q)) for q in questions_in(prev_out.payload["text"])]
            asked = [(q, a) for q, a in asked if a]
            for q, attr in asked:
                if any(o[0] == attr for o in out):
                    continue
                v = extract_answer(attr, text)
                if v is None and len(asked) == 1 and attr not in ("email", "phone", "preferred_name"):
                    v = first_sentence(text)
                if v:
                    out.append((attr, v, "STATED_IN_REPLY"))
        written = []
        for attr, v, basis in out:
            ev = self.assert_fact(cid, attr, v, basis=basis, actor=TOOL_ACTOR, source_event=mid,
                                  privacy=msg_ev.header["privacy"])
            if ev is not None:
                written.append(ev)
        return written

    def _last_outgoing_before(self, cid, msg_ev):
        msgs = sorted(self._message_events(cid), key=lambda e: (e.payload["sent_at"], event_id_for(e.header)))
        prev = None
        for e in msgs:
            if event_id_for(e.header) == event_id_for(msg_ev.header):
                break
            if e.payload["conversation_id"] == msg_ev.payload["conversation_id"]:
                prev = e
        # only a reply that directly follows our message answers its questions
        return prev if prev is not None and prev.payload["direction"] == "OUT" else None

    def add_commitment(self, cid: str, text: str, *, owed_by: str, actor: str, due: Optional[str] = None,
                       source_event: Optional[str] = None) -> str:
        cmid = "cm_" + digest("commitment", [cid, owed_by, text, due])[:24]
        payload = {"commitment_id": cmid, "contact_id": cid, "text": text, "owed_by": owed_by}
        if due:
            payload["due"] = due
        self.node.append("COMMITMENT_RECORDED", payload, actor=actor, links=[entity(cid)], privacy="PRIVATE",
                         provenance=[{"kind": "derived_from", "ref": source_event}] if source_event
                         else [{"kind": "source", "ref": "operator:entry"}])
        return cmid

    def set_commitment_status(self, cid: str, cmid: str, status: str, *, actor: str):
        key = f"commitment|{cmid}|status"
        return self.node.append("COMMITMENT_STATUS", {"commitment_id": cmid, "status": status}, actor=actor,
                                links=[entity(cid)], privacy="PRIVATE",
                                parents=reconcile.current_heads(self.node, key))

    # ------------------------------------------------------- reconstruction
    def contacts(self) -> list:
        return sorted({e.payload["contact_id"] for e in self.node.events("CONTACT_ASSERTED") if e.payload})

    def context(self, cid: str) -> dict:
        """Reconstruct the conversational state for one contact (deterministic;
        uses only events linked to this contact)."""
        ent = entity(cid)
        evs = [e for e in self.node.events(entity=ent) if e.payload is not None]
        profile = {"contact_id": cid, "aliases": set(), "channels": set(), "boundaries": set()}
        for e in evs:
            if e.header["event_type"] == "CONTACT_ASSERTED":
                profile["aliases"] |= set(e.payload.get("aliases", []))
                profile["channels"] |= {(c["kind"], c["address"]) for c in e.payload.get("channels", [])}
                profile["boundaries"] |= set(e.payload.get("boundaries", []))
        name = reconcile.resolve(self.node, f"contact|{cid}|display_name")
        profile = {"contact_id": cid, "display_name": name["value"], "display_name_status": name["status"],
                   "aliases": sorted(profile["aliases"]), "channels": sorted(list(c) for c in profile["channels"]),
                   "boundaries": sorted(profile["boundaries"])}
        facts = {}
        for key, r in sorted(reconcile.assertions_by_key(self.node, f"fact|{ent}|").items()):
            res = reconcile.resolve(self.node, key, r)
            facts[key.split("|", 2)[2]] = {k: res[k] for k in ("value", "status", "heads", "evidence")}
        msgs = sorted((e for e in evs if e.header["event_type"] == "MESSAGE_RECORDED"),
                      key=lambda e: (e.payload["sent_at"], event_id_for(e.header)))
        timeline = [{"event_id": event_id_for(e.header), "direction": e.payload["direction"],
                     "sent_at": e.payload["sent_at"], "conversation_id": e.payload["conversation_id"],
                     "text": e.payload["text"], "source": e.header["provenance"][0]["ref"]} for e in msgs]
        answered, open_q = [], []
        for i, m in enumerate(timeline):
            if m["direction"] != "OUT":
                continue
            reply = next((r for r in timeline[i + 1:] if r["direction"] == "IN"
                          and r["conversation_id"] == m["conversation_id"]), None)
            for q in questions_in(m["text"]):
                item = {"question": q, "attribute": classify_question(q), "asked_in": m["event_id"]}
                if reply:
                    answered.append({**item, "answered_in": reply["event_id"]})
                else:
                    open_q.append(item)
        commitments = []
        for e in evs:
            if e.header["event_type"] == "COMMITMENT_RECORDED":
                st = reconcile.resolve(self.node, f"commitment|{e.payload['commitment_id']}|status")
                commitments.append({"commitment_id": e.payload["commitment_id"], "text": e.payload["text"],
                                    "owed_by": e.payload["owed_by"], "due": e.payload.get("due"),
                                    "status": st["value"] or "OPEN", "status_state": st["status"] if st["heads"] else "DEFAULT",
                                    "event_id": event_id_for(e.header)})
        commitments.sort(key=lambda c: c["commitment_id"])
        return {"contact": profile, "facts": facts, "timeline": timeline, "answered_questions": answered,
                "open_questions": open_q, "commitments": commitments}

    def context_digest(self, cid: str) -> str:
        return "cx_" + digest("context", self.context(cid))

    # ------------------------------------------------------------- checks
    def check_draft(self, cid: str, text: str, today: Optional[str] = None,
                    semantic_checker: Optional[Callable[[list, str], bool]] = None) -> list:
        """Findings for a draft to `cid`. severity BLOCK means do not send.

        semantic_checker(answered_pairs, question) -> bool is optional (e.g. a
        local model, forge.OllamaClient.repeat_checker). Its hits are WARN
        (POSSIBLE_REPEAT), never BLOCK: in the memory benchmark it raised recall
        but had more false positives than the rules (BENCHMARK_REPORT.md). If it
        fails, the check degrades to the rules alone."""
        ctx = self.context(cid)
        findings = []
        known = {a: f for a, f in ctx["facts"].items() if f["status"] == "RESOLVED"}
        # repeated / pending questions
        for q in questions_in(text):
            attr = classify_question(q)
            if attr and attr in known:
                findings.append({"code": "REPEATED_QUESTION", "severity": "BLOCK", "question": q,
                                 "attribute": attr, "known_value": known[attr]["value"],
                                 "evidence": known[attr]["heads"] + known[attr]["evidence"]})
                continue
            qt = tokens(q)
            hit = next((a for a in ctx["answered_questions"]
                        if (attr and a["attribute"] == attr) or jaccard(qt, tokens(a["question"])) >= 0.5), None)
            if hit:
                findings.append({"code": "REPEATED_QUESTION", "severity": "BLOCK", "question": q,
                                 "attribute": hit["attribute"], "previously_asked": hit["question"],
                                 "evidence": [hit["asked_in"], hit["answered_in"]]})
                continue
            pend = next((a for a in ctx["open_questions"]
                         if (attr and a["attribute"] == attr) or jaccard(qt, tokens(a["question"])) >= 0.5), None)
            if pend:
                findings.append({"code": "ALREADY_ASKED_PENDING", "severity": "WARN", "question": q,
                                 "evidence": [pend["asked_in"]]})
                continue
            if semantic_checker is not None and ctx["answered_questions"]:
                pairs = []
                for aq in ctx["answered_questions"]:
                    ans = next((m["text"] for m in ctx["timeline"] if m["event_id"] == aq["answered_in"]), "")
                    pairs.append({"q": aq["question"], "a": ans})
                try:
                    if semantic_checker(pairs, q):
                        findings.append({"code": "POSSIBLE_REPEAT", "severity": "WARN", "question": q,
                                         "checker": getattr(semantic_checker, "name", "semantic"),
                                         "evidence": [a["answered_in"] for a in ctx["answered_questions"]]})
                except Exception as exc:
                    findings.append({"code": "SEMANTIC_CHECK_UNAVAILABLE", "severity": "INFO",
                                     "detail": type(exc).__name__})
        # identity
        m = GREETING_RE.match(text)
        if m:
            used = m.group(1).lower()
            names = set()
            if ctx["contact"]["display_name"]:
                names |= {p.lower() for p in ctx["contact"]["display_name"].split()}
            names |= {a.lower() for al in ctx["contact"]["aliases"] for a in al.split()}
            if "preferred_name" in known:
                names.add(known["preferred_name"]["value"].lower())
            if names and used not in names:
                findings.append({"code": "MISTAKEN_IDENTITY", "severity": "BLOCK", "name_used": m.group(1),
                                 "expected_one_of": sorted(names)})
            elif "preferred_name" in known and used != known["preferred_name"]["value"].lower():
                findings.append({"code": "PREFERRED_NAME_IGNORED", "severity": "WARN", "name_used": m.group(1),
                                 "preferred": known["preferred_name"]["value"],
                                 "evidence": known["preferred_name"]["evidence"]})
        # contradictions with known facts
        if "budget" in known:
            kv = money_value(known["budget"]["value"])
            for mm in MONEY_RE.finditer(text):
                if "budget" in text.lower() and kv is not None and money_value(mm.group(0)) != kv:
                    findings.append({"code": "CONTRADICTION", "severity": "BLOCK", "attribute": "budget",
                                     "draft_value": mm.group(0), "known_value": known["budget"]["value"],
                                     "evidence": known["budget"]["evidence"]})
        for attr, rx in (("email", EMAIL_RE),):
            if attr in known:
                for mm in rx.finditer(text):
                    if mm.group(0).lower() != known[attr]["value"].lower():
                        findings.append({"code": "CONTRADICTION", "severity": "BLOCK", "attribute": attr,
                                         "draft_value": mm.group(0), "known_value": known[attr]["value"]})
        # boundaries
        low = text.lower()
        for attr, f in known.items():
            if attr.startswith("boundary:"):
                verb = attr.split(":", 1)[1]
                terms = WEEKEND_TERMS if verb == "weekend" else BOUNDARY_TERMS.get(verb, [])
                if any(re.search(t, low) for t in terms):
                    findings.append({"code": "BOUNDARY_CONFLICT", "severity": "BLOCK", "boundary": f["value"],
                                     "evidence": f["evidence"]})
        # cross-contact isolation
        own_values = {f["value"].lower() for f in ctx["facts"].values() if f["value"]}
        own_names = {n.lower() for n in [ctx["contact"]["display_name"] or ""] + ctx["contact"]["aliases"] if n}
        for other in self.contacts():
            if other == cid:
                continue
            octx = self.context(other)
            oname = octx["contact"]["display_name"]
            own_tokens = {t for n in own_names for t in n.split()}
            other_names = {n for n in [oname] + octx["contact"]["aliases"] if n}
            other_names |= {t for n in other_names for t in n.split()}
            for n in sorted(other_names):
                if len(n) >= 4 and n.lower() not in own_names and n.lower() not in own_tokens \
                        and re.search(rf"\b{re.escape(n.lower())}\b", low):
                    findings.append({"code": "CROSS_CONTACT_REFERENCE", "severity": "WARN", "other_contact": other})
                    break
            for attr, f in octx["facts"].items():
                v = (f["value"] or "")
                if len(v) >= 4 and v.lower() not in own_values and v.lower() in low:
                    findings.append({"code": "PRIVACY_LEAK", "severity": "BLOCK", "other_contact": other,
                                     "attribute": attr})
        # obligations
        today = today or date.today().isoformat()
        for c in ctx["commitments"]:
            if c["owed_by"] == "US" and c["status"] == "OPEN":
                overdue = bool(c["due"] and c["due"] < today)
                findings.append({"code": "OVERDUE_OBLIGATION" if overdue else "OPEN_OBLIGATION",
                                 "severity": "WARN" if overdue else "INFO", "commitment": c["text"],
                                 "due": c["due"], "evidence": [c["event_id"]]})
        return findings

    # -------------------------------------------------------------- draft
    def compose(self, cid: str, intent: str = "follow_up", *, sender: str = "", today: Optional[str] = None,
                generator: Optional[Callable[[dict, str], str]] = None, record: bool = True) -> dict:
        ctx = self.context(cid)
        known = {a: f for a, f in ctx["facts"].items() if f["status"] == "RESOLVED"}
        first = (known.get("preferred_name", {}).get("value")
                 or (ctx["contact"]["display_name"] or "there").split()[0])
        lines = [f"Hi {first},", ""]
        last = ctx["timeline"][-1] if ctx["timeline"] else None
        if last and last["direction"] == "IN":
            lines.append("Thank you for getting back to me.")
            learned = [(a, f) for a, f in known.items() if a in ("goal", "timeline", "budget")
                       and last["event_id"] in f["evidence"]]
            for a, f in learned:
                lines.append(f"Noted on your {a}: {f['value'].rstrip('.!?')}.")
        for c in ctx["commitments"]:
            if c["owed_by"] == "US" and c["status"] == "OPEN":
                lines.append(f"I have not forgotten that I owe you: {c['text']}"
                             + (f" (due {c['due']})." if c["due"] else "."))
        pending_attrs = {q["attribute"] for q in ctx["open_questions"] if q["attribute"]}
        nxt = next((a for a in INTENT_PLANS.get(intent, []) if a not in known and a not in pending_attrs
                    and a in QUESTION_TEMPLATES), None)
        if nxt:
            lines.append(QUESTION_TEMPLATES[nxt])
        elif intent != "follow_up":
            lines.append("I have what I need for the next step and will send it over shortly.")
        lines += ["", "Best regards" + (f",\n{sender}" if sender else ".")]
        text = "\n".join(lines)
        generator_name, rejected = "deterministic-template", None
        if generator is not None:
            try:
                cand = generator(ctx, intent)
                cf = self.check_draft(cid, cand, today)
                if cand and not any(f["severity"] == "BLOCK" for f in cf):
                    text, generator_name = cand, getattr(generator, "name", "generator")
                else:
                    rejected = {"reason": "failed draft checks", "codes": sorted({f["code"] for f in cf})}
            except Exception as exc:  # optional capability degrades gracefully
                rejected = {"reason": f"generator unavailable: {type(exc).__name__}"}
        findings = self.check_draft(cid, text, today)
        result = {"text": text, "findings": findings, "generator": generator_name, "next_question": nxt,
                  "generator_rejected": rejected, "context_digest": "cx_" + digest("context", ctx)}
        if record:
            parents = [last["event_id"]] if last else []
            ev = self.node.append("DRAFT_PRODUCED", {"contact_id": cid, "text": text, "generator": generator_name,
                                                     "findings": [f["code"] for f in findings], "intent": intent,
                                                     "context_digest": result["context_digest"]},
                                  actor=TOOL_ACTOR if generator_name == "deterministic-template" else f"model:{generator_name}",
                                  links=[entity(cid)], privacy="PRIVATE", parents=parents,
                                  provenance=[{"kind": "derived_from", "ref": result["context_digest"]}])
            result["event_id"] = event_id_for(ev.header)
        return result
