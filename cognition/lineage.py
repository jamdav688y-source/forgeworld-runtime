"""FW-COGNITIVE-R2-001 (A): Cognitive Lineage -- read-only ancestry queries
over accepted CXP records.

Every function here takes `lookup(record_id) -> metadata | None` (normally
CognitiveExchange.record_metadata) and never writes anything. Results are
plain dicts with every list sorted, so the same store always yields the
same answer.

What a trace answers:
  - which original source observations a record rests on (observation_roots)
    and which sources those cite, each with its independence_basis:
      DEFAULT   the independence key is the source's own id (one source,
                one origin);
      DECLARED  the emitter grouped sources under a shared key. CXP cannot
                verify that declaration -- it is reported, not trusted.
  - whether the record is DIRECT_OBSERVATION, RESTATEMENT (only quotation/
    paraphrase steps between it and its observations) or INFERRED (some
    step is an inference, hypothesis, simulation, dramatization, or an
    unverified interpretation).
  - which records in a set are repeated derivatives of the same origin
    (shared_origins), so repetition is never mistaken for corroboration.

Defensive integrity checks (content addressing makes these impossible in
an untampered store, so hitting one means the store or the lookup is
corrupt): CYCLE, DANGLING_REFERENCE, MALFORMED_METADATA (including root
sources that disagree with what was recorded at ingest), DEPTH_EXCEEDED.

Privacy: a node is REDACTED when it is erased or its privacy class is above
the caller's clearance. A redacted node keeps its id, kind and epistemic
labels but loses nothing else to the caller; a source cited only by
redacted roots loses its locator and its declared key (replaced by an
opaque digest). The underlying ledger still holds those values -- see the
R2 report on residual metadata.
"""
from __future__ import annotations

import hashlib
from typing import Callable, Optional

from cognition import cxp

DIRECT_OBSERVATION = "DIRECT_OBSERVATION"
RESTATEMENT = "RESTATEMENT"
INFERRED = "INFERRED"

BASIS_DEFAULT = "DEFAULT"
BASIS_DECLARED = "DECLARED"

E_UNKNOWN_RECORD = "UNKNOWN_RECORD"
E_CYCLE = "CYCLE"
E_DANGLING_REFERENCE = "DANGLING_REFERENCE"
E_MALFORMED_METADATA = "MALFORMED_METADATA"
E_DEPTH_EXCEEDED = "DEPTH_EXCEEDED"

MAX_DEPTH = 256

_INFERENTIAL_REPRESENTATIONS = (cxp.REP_INFERENCE, cxp.REP_HYPOTHESIS, cxp.REP_SIMULATION, cxp.REP_DRAMATIZATION)
_ROOT_KINDS = (cxp.KIND_OBSERVATION, cxp.KIND_VERIFICATION_RESULT)
_REQUIRED_KEYS = ("record_id", "kind", "representation", "provenance", "evidence", "verification", "privacy",
                  "sources", "root_sources", "derived_from", "erased")


class LineageError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _check_metadata(meta, record_id: str) -> None:
    if not isinstance(meta, dict) or any(k not in meta for k in _REQUIRED_KEYS):
        raise LineageError(E_MALFORMED_METADATA, f"{record_id} metadata is missing required fields")
    if meta["record_id"] != record_id or meta["kind"] not in cxp.ENABLED_KINDS:
        raise LineageError(E_MALFORMED_METADATA, f"{record_id} metadata does not describe that record")
    parents = meta["derived_from"]
    if not isinstance(parents, list) or not all(isinstance(p, str) for p in parents):
        raise LineageError(E_MALFORMED_METADATA, f"{record_id} derived_from is not a list of ids")
    if meta["kind"] in _ROOT_KINDS:
        if parents or not meta["sources"]:
            raise LineageError(E_MALFORMED_METADATA, f"{record_id} is a root kind but has parents or no sources")
    elif not parents or meta["sources"]:
        raise LineageError(E_MALFORMED_METADATA, f"{record_id} is a derived kind but has no parents or own sources")


def _is_redacted(meta: dict, clearance: str) -> bool:
    return bool(meta["erased"]) or cxp.PRIVACY_CLASSES.index(meta["privacy"]) > cxp.PRIVACY_CLASSES.index(clearance)


def _collect(lookup: Callable[[str], Optional[dict]], record_id: str) -> tuple:
    """Depth-first walk with an explicit path for cycle detection. Returns
    ({record_id: metadata}, {record_id: shortest depth from the query})."""
    nodes, depth = {}, {}

    def visit(rid: str, d: int, path: frozenset) -> None:
        if rid in path:
            raise LineageError(E_CYCLE, f"{rid} is its own ancestor")
        if d > MAX_DEPTH:
            raise LineageError(E_DEPTH_EXCEEDED, f"ancestry deeper than {MAX_DEPTH}")
        if rid in depth and depth[rid] <= d:
            return  # already fully explored at least this close to the query
        meta = lookup(rid)
        if meta is None:
            raise LineageError(E_UNKNOWN_RECORD if d == 0 else E_DANGLING_REFERENCE,
                               f"{rid} is not an accepted record")
        _check_metadata(meta, rid)
        nodes[rid], depth[rid] = meta, d
        for parent in meta["derived_from"]:
            visit(parent, d + 1, path | {rid})

    visit(record_id, 0, frozenset())
    return nodes, depth


def _origin_label(source: dict, redacted: bool) -> str:
    if source["independence_key"] == source["source_id"] or not redacted:
        return source["independence_key"]
    return "redacted-origin-" + hashlib.sha256(source["independence_key"].encode("utf-8")).hexdigest()[:32]


def trace(lookup: Callable[[str], Optional[dict]], record_id: str, clearance: str = cxp.PRIV_INTERNAL) -> dict:
    if clearance not in cxp.PRIVACY_CLASSES:
        raise ValueError(f"clearance must be one of {cxp.PRIVACY_CLASSES}")
    nodes, depth = _collect(lookup, record_id)
    query = nodes[record_id]

    roots = sorted(rid for rid, meta in nodes.items() if meta["kind"] in _ROOT_KINDS)
    sources, cited_by = {}, {}
    for rid in roots:
        for source in nodes[rid]["sources"]:
            sources[source["source_id"]] = source
            cited_by.setdefault(source["source_id"], []).append(rid)
    recorded = sorted(s["source_id"] for s in query["root_sources"])
    if recorded != sorted(sources):
        raise LineageError(E_MALFORMED_METADATA, f"{record_id} root sources disagree with its recorded lineage")

    redacted = {rid: _is_redacted(meta, clearance) for rid, meta in nodes.items()}
    source_rows = []
    for source_id in sorted(sources):
        source = sources[source_id]
        hidden = all(redacted[rid] for rid in cited_by[source_id])
        source_rows.append({
            "source_id": source_id,
            "source_type": source["source_type"],
            "locator": None if hidden else source["locator"],
            "origin": _origin_label(source, hidden),
            "independence_basis": BASIS_DEFAULT if source["independence_key"] == source_id else BASIS_DECLARED,
            "cited_by": sorted(cited_by[source_id]),
            "redacted": hidden,
        })

    if query["kind"] in _ROOT_KINDS:
        epistemic_class = DIRECT_OBSERVATION
    elif any(meta["kind"] not in _ROOT_KINDS and (meta["representation"] in _INFERENTIAL_REPRESENTATIONS
                                                  or meta["provenance"] == cxp.UNVERIFIED_INTERPRETATION)
             for meta in nodes.values()):
        epistemic_class = INFERRED
    else:
        epistemic_class = RESTATEMENT

    return {
        "record_id": record_id,
        "clearance": clearance,
        "epistemic_class": epistemic_class,
        "max_derivation_depth": max(depth.values()),
        "observation_roots": roots,
        "sources": source_rows,
        "distinct_source_count": len(source_rows),
        "independent_origin_count": len({row["origin"] for row in source_rows}),
        "nodes": [
            {"record_id": rid, "kind": nodes[rid]["kind"], "representation": nodes[rid]["representation"],
             "provenance": nodes[rid]["provenance"], "evidence": nodes[rid]["evidence"],
             "verification": nodes[rid]["verification"], "depth": depth[rid],
             "parents": sorted(nodes[rid]["derived_from"]), "erased": bool(nodes[rid]["erased"]),
             "redacted": redacted[rid]}
            for rid in sorted(nodes, key=lambda r: (depth[r], r))
        ],
    }


def shared_origins(lookup: Callable[[str], Optional[dict]], record_ids, clearance: str = cxp.PRIV_INTERNAL) -> dict:
    """Group records by the origins they trace back to. A record appearing in
    the same origin group as another is NOT independent of it, however many
    restatements exist; independent_origin_count is the only count that may
    be read as corroboration breadth."""
    groups = {}
    for record_id in sorted(set(record_ids)):
        for origin in {row["origin"] for row in trace(lookup, record_id, clearance)["sources"]}:
            groups.setdefault(origin, []).append(record_id)
    return {
        "records": sorted(set(record_ids)),
        "origins": {origin: sorted(rids) for origin, rids in sorted(groups.items())},
        "repeated_origins": sorted(origin for origin, rids in groups.items() if len(rids) > 1),
        "independent_origin_count": len(groups),
    }
