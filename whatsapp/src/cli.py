#!/usr/bin/env python3
"""Phone-first command surface (mission Section 15).

Minimum actions: review, edit, approve, reject, escalate,
request-more-evidence, schedule-follow-up, mark-not-opportunity, stop
(emergency outbound stop). This CLI is the command surface; it does not do
heavy processing -- it only reads/writes the jsonl ledgers and config.json.
"""
import argparse
import json
import sys

from . import approval, ledger, modes


def cmd_status(args):
    mode = modes.get_mode()
    pending = approval.list_pending()
    conv = ledger.read_all(ledger.CONVERSATION_LEDGER)
    print("========== FORGEWORLD WHATSAPP STATUS ==========")
    print(f"Mode: inbound={mode['inbound']} outbound={mode['outbound']} "
          f"campaign={mode['campaign']} autonomous_commitments={mode['autonomous_commitments']}")
    print(f"Conversation events ledgered: {len(conv)}")
    print(f"Drafts awaiting approval: {len(pending)}")
    print("=================================================")


def cmd_review(args):
    pending = approval.list_pending()
    if not pending:
        print("No drafts awaiting approval.")
        return
    for p in pending:
        print(f"draft_id={p['draft_id']} event_id={p['event_id']} action={p['action']}")


def cmd_approve(args):
    record = approval.approve(args.draft_id, args.actor, args.note or "")
    print(json.dumps(record, indent=2))


def cmd_reject(args):
    record = approval.reject(args.draft_id, args.actor, args.note or "")
    print(json.dumps(record, indent=2))


def cmd_escalate(args):
    record = approval.escalate(args.draft_id, args.actor, args.note or "")
    print(json.dumps(record, indent=2))


def cmd_request_more_evidence(args):
    record = approval.request_more_evidence(args.draft_id, args.actor, args.note or "")
    print(json.dumps(record, indent=2))


def cmd_mark_not_opportunity(args):
    record = approval.mark_not_opportunity(args.draft_id, args.actor, args.note or "")
    print(json.dumps(record, indent=2))


def cmd_schedule_follow_up(args):
    record = approval.schedule_follow_up(args.draft_id, args.actor, args.follow_up_at, args.note or "")
    print(json.dumps(record, indent=2))


def cmd_stop(args):
    mode = modes.emergency_stop()
    print("EMERGENCY STOP applied. Outbound delivery disabled immediately.")
    print(json.dumps(mode, indent=2))


def cmd_resume(args):
    mode = modes.resume_draft_mode()
    print("Outbound resumed in DRAFT_ONLY mode (never auto-resumes to a higher tier).")
    print(json.dumps(mode, indent=2))


def build_parser():
    parser = argparse.ArgumentParser(prog="forge-whatsapp", description="Phone-first WhatsApp membrane control surface.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Channel health, mode, pending count").set_defaults(func=cmd_status)
    sub.add_parser("review", help="List drafts awaiting approval").set_defaults(func=cmd_review)

    for name, fn, needs_note in [
        ("approve", cmd_approve, True),
        ("reject", cmd_reject, True),
        ("escalate", cmd_escalate, True),
        ("request-more-evidence", cmd_request_more_evidence, True),
        ("mark-not-opportunity", cmd_mark_not_opportunity, True),
    ]:
        p = sub.add_parser(name)
        p.add_argument("draft_id")
        p.add_argument("--actor", required=True, help="who is making this decision")
        p.add_argument("--note", default="")
        p.set_defaults(func=fn)

    p = sub.add_parser("schedule-follow-up")
    p.add_argument("draft_id")
    p.add_argument("--actor", required=True)
    p.add_argument("--follow-up-at", dest="follow_up_at", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_schedule_follow_up)

    sub.add_parser("stop", help="EMERGENCY STOP: disable all outbound delivery immediately").set_defaults(func=cmd_stop)
    sub.add_parser("resume", help="Resume outbound in DRAFT_ONLY mode after a stop").set_defaults(func=cmd_resume)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
