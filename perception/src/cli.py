#!/usr/bin/env python3
"""Phone-first command surface for the Perception Gateway, mirroring
whatsapp/src/cli.py's structure and role exactly ("the command surface;
it does not do heavy processing -- it only reads/writes the jsonl ledgers").
This *is* Mission Control for this system -- no dashboard is introduced.

Offline by construction: `run` takes --ocr-fixtures/--retrieval-fixtures
JSON files rather than talking to a live provider (see ocr.py/retrieval.py's
documented-but-unwired CloudOCRProvider/WebSearchProvider for where a real
provider would plug in later).
"""
import argparse
import json
import sys

from whatsapp.src import ledger as wa_ledger

from . import ocr, pipeline, promotion, retrieval, schema


def _load_fixture_provider(kind: str, path: str):
    with open(path) as f:
        data = json.load(f)
    if kind == "ocr":
        return ocr.FixtureOCRProvider(data)
    if kind == "retrieval":
        return retrieval.FixtureRetrievalProvider(data)
    raise ValueError(kind)


def cmd_ingest(args):
    from . import ingest
    observation = ingest.ingest_image(args.path, args.capture_source, args.device_note or "")
    print(json.dumps(observation, indent=2, sort_keys=True))


def cmd_run(args):
    ocr_provider = _load_fixture_provider("ocr", args.ocr_fixtures)
    retrieval_provider = _load_fixture_provider("retrieval", args.retrieval_fixtures)
    result = pipeline.run_pipeline(
        args.path, args.capture_source, ocr_provider, retrieval_provider,
        device_note=args.device_note or "", decided_by=args.decided_by,
    )

    print("========== FORGEWORLD PERCEPTION GATEWAY ==========")
    print(f"OBSERVATION: {result['observation']['id']} "
          f"({result['observation']['width']}x{result['observation']['height']}, "
          f"sha256={result['observation']['source_image_sha256'][:12]}...)")
    print(f"  OCR text: {result['signals']['ocr']['value']!r}")
    print(f"  fingerprint: {result['signals']['fingerprint']['value']}")
    print(f"  entities: {[s['value'] for s in result['signals']['entities']]}")
    print(f"INFERENCE: {len(result['candidates'])} candidate source(s) retrieved (all start CANDIDATE_MATCH)")
    print(f"VALIDATION: {len(result['relationships'])} relationship(s), "
          f"{len(result['contradictions'])} unresolved contradiction(s), "
          f"{len(result['claims'])} claim(s)")
    for c in result["claims"]:
        print(f"  claim [{c['validation_status']}]: {c['claim_text']}")
    print(f"PROMOTION: {len(result['proposals'])} proposal(s) (validation_status is always PROPOSED)")
    if not args.decided_by:
        print("  no --decided-by supplied: pipeline halted here. A human must run "
              "`forge-perception review` and `forge-perception promote <id> --actor <human>` next.")
    else:
        for d in result["promotion_decisions"]:
            print(f"  decision [{d['decision']}]: {d['reason']}")
    print("=====================================================")


def cmd_status(args):
    records = [r for r in wa_ledger.read_all(wa_ledger.EXECUTION_LEDGER) if r.get("system") == "perception"]
    by_stage = {}
    for r in records:
        by_stage.setdefault(r["stage"], 0)
        by_stage[r["stage"]] += 1
    print("========== PERCEPTION GATEWAY STATUS ==========")
    print(f"Ledger entries (system=perception): {len(records)}")
    for stage, count in sorted(by_stage.items()):
        print(f"  {stage}: {count}")
    vault_entries = wa_ledger.read_all(promotion.KNOWLEDGE_VAULT)
    print(f"Knowledge Vault entries: {len(vault_entries)}")
    print("=================================================")


def _pending_proposals():
    """PROPOSED proposals with no later HUMAN_PROMOTION_GATE/DECIDED entry
    for the same proposal_id -- read straight from the execution ledger,
    the same "full record lives in the ledger" pattern whatsapp/src/draft.py
    and approval.py already use for pending drafts."""
    records = wa_ledger.read_all(wa_ledger.EXECUTION_LEDGER)
    proposed = {r["proposal_id"]: r["proposal"] for r in records
                if r.get("system") == "perception" and r.get("stage") == "CAPABILITY_PROPOSAL"
                and r.get("state") == "PROPOSED" and "proposal" in r}
    decided_ids = {r["proposal_id"] for r in records
                   if r.get("system") == "perception" and r.get("stage") == "HUMAN_PROMOTION_GATE"
                   and r.get("state") == "DECIDED"}
    return {pid: prop for pid, prop in proposed.items() if pid not in decided_ids}


def _claims_by_id_for(proposal: dict) -> dict:
    records = wa_ledger.read_all(wa_ledger.EXECUTION_LEDGER)
    claims_by_id = {}
    for r in records:
        if r.get("system") == "perception" and r.get("stage") == "CLAIM_EXTRACTION" and "claim" in r:
            claim = r["claim"]
            if claim["id"] in proposal["evidence_references"]:
                claims_by_id[claim["id"]] = claim
    return claims_by_id


def cmd_review(args):
    pending = _pending_proposals()
    if not pending:
        print("No proposals awaiting a promotion decision.")
        return
    for pid, prop in pending.items():
        print(f"proposal_id={pid}")
        print(f"  text: {prop['proposed_capability_text']}")
        print(f"  rationale: {prop['rationale']}")
        print(f"  confidence: {prop['confidence']}")


def cmd_promote(args):
    pending = _pending_proposals()
    proposal = pending.get(args.proposal_id)
    if proposal is None:
        print(f"No pending proposal with id {args.proposal_id!r} (already decided, or unknown).", file=sys.stderr)
        sys.exit(1)

    claims_by_id = _claims_by_id_for(proposal)
    fake_observation = {
        "source_image_id": proposal["source_image_id"],
        "source_image_sha256": proposal["source_image_sha256"],
        "id": proposal["source_image_id"],
    }
    decision = promotion.evaluate_promotion(fake_observation, proposal, claims_by_id, args.actor)
    print(json.dumps(decision, indent=2, sort_keys=True))
    if decision["decision"] == "PROMOTED":
        promotion.write_to_knowledge_vault(proposal, decision)
        print("Written to Knowledge Vault.")


def cmd_vault(args):
    entries = wa_ledger.read_all(promotion.KNOWLEDGE_VAULT)
    if not entries:
        print("Knowledge Vault is empty.")
        return
    for e in entries:
        print(f"{e['promotion_decision']['id']}: {e['proposal']['proposed_capability_text']}")


def build_parser():
    parser = argparse.ArgumentParser(prog="forge-perception", description="Perception Gateway control surface.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="CAPTURE + HASH a source image into governed storage")
    p.add_argument("path")
    p.add_argument("--capture-source", required=True)
    p.add_argument("--device-note", default="")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("run", help="Run the full offline pipeline against fixture providers")
    p.add_argument("path")
    p.add_argument("--capture-source", required=True)
    p.add_argument("--ocr-fixtures", required=True, help="JSON file: {sha256: {text, confidence}}")
    p.add_argument("--retrieval-fixtures", required=True, help="JSON file: {query: [{url,title,snippet,confidence}]}")
    p.add_argument("--device-note", default="")
    p.add_argument("--decided-by", default=None, help="human identifier; omit to stop before promotion")
    p.set_defaults(func=cmd_run)

    sub.add_parser("status", help="Perception Gateway ledger + vault counts").set_defaults(func=cmd_status)
    sub.add_parser("review", help="List proposals awaiting a promotion decision").set_defaults(func=cmd_review)

    p = sub.add_parser("promote", help="Human promotion decision for a pending proposal")
    p.add_argument("proposal_id")
    p.add_argument("--actor", required=True, help="human identifier making this decision")
    p.set_defaults(func=cmd_promote)

    sub.add_parser("vault", help="List Knowledge Vault entries").set_defaults(func=cmd_vault)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
