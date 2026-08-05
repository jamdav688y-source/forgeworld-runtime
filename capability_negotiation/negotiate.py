#!/usr/bin/env python3
"""CLI for the Capability Negotiation Engine.

Usage:
  python3 capability_negotiation/negotiate.py --mission windows_desktop_deployment
  python3 capability_negotiation/negotiate.py --mission cinema_release_commit \
      --live-connectors Airtable,Gmail,Google Drive,Slack,Zapier
  python3 capability_negotiation/negotiate.py --mission windows_desktop_deployment --resume

--live-connectors only carries evidence the calling agent actually
observed (e.g. via a ListConnectors-style tool call) -- this CLI does not
and cannot query that itself; omit the flag and connector-backed
requirements correctly resolve to OPERATOR_REQUIRED instead of a guess.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine  # noqa: E402
from missions import MISSIONS  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Negotiate whether the current environment can run a mission.")
    parser.add_argument("--mission", required=True, choices=sorted(MISSIONS))
    parser.add_argument("--live-connectors", default="", help="Comma-separated list of connector names known-connected right now.")
    parser.add_argument("--resume", action="store_true", help="Compare against the last published report and flag newly-resolved gaps.")
    args = parser.parse_args()

    live = [c.strip() for c in args.live_connectors.split(",") if c.strip()] or None

    if args.resume:
        outcome = engine.check_resume(args.mission, live_connectors=live)
        json.dump(outcome, sys.stdout, indent=2)
        print()
        sys.exit(0 if outcome["can_proceed_now"] else 1)

    result = engine.negotiate(args.mission, live_connectors=live)
    out_dir = engine.publish_report(result)
    print(f"Report published to: {out_dir}", file=sys.stderr)
    json.dump(result.as_dict(), sys.stdout, indent=2)
    print()
    sys.exit(0 if result.can_proceed else 1)


if __name__ == "__main__":
    main()
