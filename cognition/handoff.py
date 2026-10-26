"""FW-ENTERPRISE R1: read-only, checksum-verified production handoff.

A handoff exports ONE approved production-package version to the people
who will prepare production, together with a human sign-off record. It
is the first delivery primitive: an immutable bundle whose every file is
checksummed, whose checksum list is anchored in CXP, and whose standing
is recomputed on every verification rather than trusted.

Preconditions (all re-checked at export, most again at ingest):
  - the package version loads intact (E2 tamper check),
  - it is the latest version (not SUPERSEDED by an E3 revision),
  - its computed E3 review status is APPROVED (a valid PACKAGE_REVIEW on
    this exact package_id, with the underlying episode-candidate approval
    still valid and no later REJECTED / NEEDS_REVISION review),
  - the signer is a human operator id and is not the editor of this
    version (the person who made the last change does not sign it off),
  - no handoff already exists for this version, and no cycle is running.

Bundle: handoffs/<handoff_id>/ holds byte-exact copies of package.json,
package.md and manifest.json, plus handoff.json (the sign-off record) and
SHA256SUMS (verifiable with `sha256sum -c SHA256SUMS`). handoff_id is the
content address of handoff.json. Files are written to a staging directory,
re-read and checked, made read-only and moved into place; only then is the
PRODUCTION_HANDOFF record ingested. A crash before ingest leaves an
unanchored bundle that verify() reports as NOT_ANCHORED and a re-run of the
same export completes; a refused ingest removes the bundle.

verify() separates INTEGRITY (are these exactly the anchored bytes?) from
CURRENCY (does the approval still stand?). A later revision, a withdrawn
candidate approval or a later negative review makes a handoff STALE; it
is never carried forward to a new version.

What a handoff is NOT: publication approval (publication_authorized is
False everywhere), evidence (labels HUMAN_ASSERTED / NONE / UNVERIFIED),
generated media, or a customer delivery. There is no upload, posting,
messaging or network code here.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from cognition import bundle, cxp, episode as ep, package_revision as rv, production as pr

HANDOFF_SCHEMA = "forgeworld.production.handoff.v1"
HANDED_OFF = "HANDED_OFF_FOR_PRODUCTION_PREPARATION"
STALE = "STALE"
INVALID = "INVALID"
PACKAGE_FILES = ("package.json", "package.md", "manifest.json")
BUNDLE_FILES = PACKAGE_FILES + ("handoff.json", "SHA256SUMS")

H_NOT_APPROVED = "NOT_APPROVED_FOR_HANDOFF"
H_SIGNER_IS_EDITOR = "SIGNER_IS_EDITOR"
H_EXISTS = "HANDOFF_EXISTS"
H_UNKNOWN_PACKAGE = "UNKNOWN_PACKAGE"

KNOWN_LIMITATIONS = (
    "DRAFT production plan: no media has been generated; visual prompts and narration are instructions only.",
    "Not publication approval: publication requires a separate, explicit human authorization.",
    "Operator identities are id strings checked by pattern; they are not authenticated.",
    "Claim-change classification is word-list based; the human package review is the semantic check.",
    "Acceptance of an uncertainty is not verification of the claim.",
)

_PAYLOAD_KEYS = frozenset({"handoff_id", "package_record_id", "package_id", "package_review_id", "signer",
                           "sums_sha256", "publication_authorized"})
_HANDOFF_ID = re.compile(r"^cxp-hof-[0-9a-f]{64}$")


class HandoffRefused(Exception):
    def __init__(self, reasons):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)


_sha = bundle.sha256_hex
render_sums = bundle.render_sums


# ---------------------------------------------------------------------------
# PRODUCTION_HANDOFF record rules (called by cxp / exchange)
# ---------------------------------------------------------------------------

def check_record_payload(payload: dict) -> None:
    if set(payload) != _PAYLOAD_KEYS:
        raise cxp.CXPError(cxp.E_MALFORMED, f"PRODUCTION_HANDOFF payload requires exactly {sorted(_PAYLOAD_KEYS)}")
    if not isinstance(payload["handoff_id"], str) or not _HANDOFF_ID.match(payload["handoff_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "handoff_id is malformed")
    for name in ("package_record_id", "package_review_id"):
        if not isinstance(payload[name], str) or not pr._RECORD_ID.match(payload[name]):
            raise cxp.CXPError(cxp.E_MALFORMED, f"{name} must be a record id")
    if not isinstance(payload["package_id"], str) or not pr._PACKAGE_ID.match(payload["package_id"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "package_id is malformed")
    if not isinstance(payload["signer"], str) or not ep._REVIEWER.match(payload["signer"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "signer must be a human operator id (operator-<slug>)")
    if not isinstance(payload["sums_sha256"], str) or not pr._SHA256.match(payload["sums_sha256"]):
        raise cxp.CXPError(cxp.E_MALFORMED, "sums_sha256 must be a sha256 hex digest")
    if payload["publication_authorized"] is not False:
        raise cxp.CXPError(cxp.E_KIND_RULE, "a production handoff never authorizes publication")


def check_record_labels(payload, provenance, representation, evidence, verification, derived_from) -> None:
    if (provenance, representation, evidence, verification) != (
            cxp.HUMAN_ASSERTED, cxp.REP_PARAPHRASE, cxp.EV_NONE, cxp.VER_UNVERIFIED):
        raise cxp.CXPError(cxp.E_KIND_RULE, "a PRODUCTION_HANDOFF is a human sign-off: HUMAN_ASSERTED, PARAPHRASE, "
                                            "NONE, UNVERIFIED")
    if list(derived_from) != sorted([payload["package_record_id"], payload["package_review_id"]]):
        raise cxp.CXPError(cxp.E_KIND_RULE, "a PRODUCTION_HANDOFF derives from exactly its package version and the "
                                            "review that approved it")


def check_transition(payload: dict, lookup, records: dict) -> None:
    package = lookup(payload["package_record_id"])
    if (package is None or package["kind"] != cxp.KIND_PRODUCTION_PACKAGE or package["erased"]
            or package["production_package"]["package_id"] != payload["package_id"]):
        raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "a handoff must target that exact PRODUCTION_PACKAGE version")
    review = lookup(payload["package_review_id"])
    if (review is None or review["kind"] != cxp.KIND_PACKAGE_REVIEW or review["erased"]
            or review["package_review"]["package_record_id"] != payload["package_record_id"]
            or review["package_review"]["decision"] != ep.APPROVED):
        raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "a handoff needs an APPROVED review of that exact package version")
    if package["production_package"]["editor"] == payload["signer"]:
        raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "the editor of a package version cannot sign off its handoff")
    for meta in records.values():
        if meta["erased"]:
            continue
        if (meta.get("production_package") or {}).get("predecessor_record_id") == payload["package_record_id"]:
            raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "that package version has been superseded")
        r = meta.get("package_review")
        if r and r["package_record_id"] == payload["package_record_id"] and r["decision"] != ep.APPROVED:
            raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, f"that package version has a {r['decision']} review")
        if (meta.get("production_handoff") or {}).get("package_record_id") == payload["package_record_id"]:
            raise cxp.CXPError(cxp.E_TRANSITION_REFUSED, "that package version has already been handed off")


# ---------------------------------------------------------------------------
# exporter
# ---------------------------------------------------------------------------

class HandoffExporter:
    def __init__(self, editor: rv.PackageEditor, root: Path):
        self.editor = editor
        self.builder = editor.builder
        self.exchange = editor.exchange
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def _handoff_of(self, *, handoff_id=None, package_record_id=None):
        for meta in self.exchange.all_record_metadata():
            h = meta.get("production_handoff")
            if h and not meta["erased"] and (h["handoff_id"] == handoff_id or h["package_record_id"] == package_record_id):
                return meta
        return None

    def _chain(self, meta: dict) -> list:
        chain = []
        while meta is not None:
            p = meta["production_package"]
            chain.append({"package_revision": p["package_revision"], "package_id": p["package_id"],
                          "package_record_id": meta["record_id"], "editor": p["editor"]})
            meta = self.exchange.record_metadata(p["predecessor_record_id"]) if p["predecessor_record_id"] else None
        return chain[::-1]

    def export(self, package_id: str, signer: str, observed_at: str) -> dict:
        if self.editor.governor._active_cycles:
            raise HandoffRefused(["SIGNER_DURING_RUNNING_CYCLE"])
        if not isinstance(signer, str) or not ep._REVIEWER.match(signer):
            raise HandoffRefused(["UNAUTHORIZED_SIGNER: a human operator id (operator-<slug>) is required"])
        meta = self.editor._record_of(package_id)
        if meta is None:
            raise HandoffRefused([H_UNKNOWN_PACKAGE])
        status = self.editor.status(package_id)  # recomputed: supersession, review validity, candidate approval
        if status["review_status"] != ep.APPROVED:
            problems = sorted({p for r in status["reviews"] for p in r["problems"]})
            raise HandoffRefused([f"{H_NOT_APPROVED}:{status['review_status']}"] + problems)
        if meta["production_package"]["editor"] == signer:
            raise HandoffRefused([H_SIGNER_IS_EDITOR])
        existing = self._handoff_of(package_record_id=meta["record_id"])
        if existing:
            raise HandoffRefused([f"{H_EXISTS}:{existing['production_handoff']['handoff_id']}"])
        loaded = self.builder.load(package_id)  # fails closed on tampering
        package, manifest = loaded["package"], loaded["manifest"]
        review = sorted((r for r in status["reviews"] if r["decision"] == ep.APPROVED and r["valid"]),
                        key=lambda r: r["review_id"])[0]

        source = self.builder.root / package_id
        files = {name: (source / name).read_bytes() for name in PACKAGE_FILES}
        disclosures = package["disclosures"]
        body = {
            "schema": HANDOFF_SCHEMA, "status": HANDED_OFF, "scope": "PRODUCTION_PREPARATION_ONLY",
            "package": {"package_id": package_id, "package_record_id": meta["record_id"],
                        "package_revision": package["revision"]["package_revision"], "package_schema": manifest["schema"]},
            "revision_chain": self._chain(meta),
            "approvals": {
                "package_review": {"review_id": review["review_id"], "reviewer": review["reviewer"]},
                "candidate_review": {"review_id": manifest["approval"]["review_id"],
                                     "reviewer": manifest["approval"]["reviewer"],
                                     "acceptance_is_not_verification": True}},
            "signoff": {"signer": signer, "signed_at": observed_at,
                        "attests": "this exact package version is approved for production preparation"},
            "lineage": {k: manifest["lineage"][k] for k in ("candidate_id", "cycle_id", "cycle_artifact_id")},
            "artifacts": [{"path": name, "sha256": _sha(files[name]), "bytes": len(files[name])} for name in PACKAGE_FILES],
            "disclosure_summary": {"contradictions": len(disclosures["contradictions"]),
                                   "unsupported_claims": len(disclosures["unsupported_claims"]),
                                   "open_questions": len(disclosures["open_questions"])},
            "known_limitations": list(KNOWN_LIMITATIONS),
            "verification": {"checksums": "sha256sum -c SHA256SUMS (run inside this directory)",
                             "anchor": "sha256 of SHA256SUMS equals sums_sha256 in the PRODUCTION_HANDOFF record",
                             "currency": "HandoffExporter.verify(handoff_id) recomputes approval standing"},
            "publication_authorized": False, "generated_media_exists": False,
        }
        handoff_id = cxp.digest_id("handoff", body)
        files["handoff.json"] = cxp.canonical_bytes(body)
        files["SHA256SUMS"] = render_sums({k: v for k, v in files.items()})
        directory = self._write_bundle(handoff_id, files)

        receipt = self.exchange.ingest({
            "schema_version": cxp.SCHEMA_VERSION, "kind": cxp.KIND_PRODUCTION_HANDOFF,
            "representation": cxp.REP_PARAPHRASE, "evidence": cxp.EV_NONE, "verification": cxp.VER_UNVERIFIED,
            "provenance": cxp.HUMAN_ASSERTED, "privacy": meta["privacy"],
            "payload": {"handoff_id": handoff_id, "package_record_id": meta["record_id"], "package_id": package_id,
                        "package_review_id": review["review_id"], "signer": signer,
                        "sums_sha256": _sha(files["SHA256SUMS"]), "publication_authorized": False},
            "sources": [], "derived_from": sorted([meta["record_id"], review["review_id"]]),
            "verification_ref": None, "consent_ref": None,
            "occurrence": {"emitter_id": signer, "observed_at": observed_at, "correlation_id": None,
                           "causation_id": None}})
        if receipt.status == "REJECTED":
            shutil.rmtree(directory, ignore_errors=True)
            raise HandoffRefused([f"{receipt.error_code}: {receipt.detail}"])
        return {"handoff_id": handoff_id, "handoff_record_id": receipt.record_id, "directory": str(directory),
                "handoff": body, "sums": files["SHA256SUMS"].decode("ascii")}

    def _write_bundle(self, handoff_id: str, files: dict) -> Path:
        try:
            return bundle.write(self.root, handoff_id, files)
        except bundle.BundleError as exc:
            raise HandoffRefused(exc.reasons) from None

    # -- verification -------------------------------------------------------------

    def verify(self, handoff_id: str) -> dict:
        integrity, currency = [], []
        directory = self.root / handoff_id
        meta = self._handoff_of(handoff_id=handoff_id)
        anchored = self.exchange.get_record(meta["record_id"]).payload() if meta else None
        if anchored is None:
            integrity.append("NOT_ANCHORED")
        present = bundle.read(directory)
        integrity += bundle.check(present, BUNDLE_FILES, anchored["sums_sha256"] if anchored else None)
        if present:
            try:
                body = json.loads(present.get("handoff.json", b"null"))
                if cxp.digest_id("handoff", body) != handoff_id:
                    integrity.append("HANDOFF_ID_MISMATCH")
                elif {a["path"]: a["sha256"] for a in body["artifacts"]} != {
                        n: _sha(present[n]) for n in PACKAGE_FILES if n in present}:
                    integrity.append("ARTIFACT_LIST_MISMATCH")
                if cxp.digest_id("package", json.loads(present.get("package.json", b"null"))) != body["package"]["package_id"]:
                    integrity.append("PACKAGE_ID_MISMATCH")
            except (ValueError, TypeError, KeyError, cxp.CXPError):
                integrity.append("HANDOFF_RECORD_UNREADABLE")
        if anchored:
            status = self.editor.status(anchored["package_id"])
            if status["review_status"] != ep.APPROVED:
                currency.append(f"{H_NOT_APPROVED}:{status['review_status']}")
            elif not any(r["review_id"] == anchored["package_review_id"] and r["valid"] for r in status["reviews"]):
                currency.append("SIGNED_OFF_REVIEW_NO_LONGER_VALID")
        verdict = INVALID if integrity else (STALE if currency else HANDED_OFF)
        return {"handoff_id": handoff_id, "status": verdict, "intact": not integrity, "current": not currency,
                "integrity_problems": integrity, "currency_problems": currency, "publication_authorized": False}

    # -- first DeliveryPackage consumer (R2a) ---------------------------------------

    def package_inputs(self, handoff_id: str) -> dict:
        """Generic DeliveryDesk.assemble() inputs for one CURRENT, INTACT
        handoff: its five files as artifacts, its CXP record as the source
        artifact, and acceptance criteria that re-check the handoff's own
        guarantees. Nothing production-specific enters the delivery core."""
        result = self.verify(handoff_id)
        if result["status"] != HANDED_OFF:
            raise HandoffRefused([f"HANDOFF_NOT_DELIVERABLE:{result['status']}"]
                                 + result["integrity_problems"] + result["currency_problems"])
        files = bundle.read(self.root / handoff_id)
        criteria = [{"criterion_id": f"ac-present-{name.lower().replace('.', '-')}", "check": "artifact_present",
                     "path": name, "description": f"{name} is included"} for name in BUNDLE_FILES]
        criteria += [
            {"criterion_id": "ac-not-publication-approval", "check": "json_equals", "path": "handoff.json",
             "key": "publication_authorized", "value": False,
             "description": "The handoff does not authorize publication"},
            {"criterion_id": "ac-handed-off", "check": "json_equals", "path": "handoff.json", "key": "status",
             "value": HANDED_OFF, "description": "The handoff record states production-preparation handoff"},
            {"criterion_id": "ac-production-lead-confirms", "check": "human_judgement",
             "description": "The receiving production lead confirms the package is complete for preparation"},
        ]
        return {"artifacts": files, "source_artifact_ids": [self._handoff_of(handoff_id=handoff_id)["record_id"]],
                "acceptance_criteria": criteria, "known_limitations": list(KNOWN_LIMITATIONS),
                "descriptions": {"package.json": "Production package (machine-readable)",
                                 "package.md": "Production package (human-readable)",
                                 "manifest.json": "Package manifest", "handoff.json": "Human sign-off record",
                                 "SHA256SUMS": "Original handoff checksum list"}}
