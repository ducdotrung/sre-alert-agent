#!/usr/bin/env python3
"""Review self-improvement proposals from the terminal."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.core.manual_review import load_paths
from alert_agent.improvement.review_state import (
    flatten_proposals,
    get_proposal,
    load_improvement_runs,
    load_review_state,
    review_proposal,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/agent_config.yaml", help="Config file path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List proposals")
    list_parser.add_argument("--status", choices=["proposed", "accepted", "rejected", "deferred", "applied", "superseded"], default=None)
    list_parser.add_argument("--limit", type=int, default=20)

    show_parser = subparsers.add_parser("show", help="Show one proposal")
    show_parser.add_argument("proposal_id")

    for command in ("accept", "reject", "defer"):
        action_parser = subparsers.add_parser(command, help=f"Mark proposal as {command}ed")
        action_parser.add_argument("proposal_id")
        action_parser.add_argument("--reviewer", required=True)
        action_parser.add_argument("--note", default="")

    return parser


def print_summary(proposal: dict[str, Any]) -> None:
    print(
        f"[{proposal.get('status', 'proposed')}] "
        f"{proposal.get('proposal_id')} "
        f"{proposal.get('type')} "
        f"source={proposal.get('source') or 'unknown'} "
        f"project={proposal.get('project') or 'all'} "
        f"risk={proposal.get('risk') or 'n/a'}"
    )
    print(f"  {proposal.get('summary', '')}")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    paths = load_paths(args.config)

    if args.command == "list":
        proposals = flatten_proposals(load_improvement_runs(paths), load_review_state(paths))
        if args.status:
            proposals = [proposal for proposal in proposals if str(proposal.get("status") or "") == args.status]
        proposals = proposals[: max(args.limit, 0)] if args.limit > 0 else proposals
        if not proposals:
            print("No proposals found")
            return 0
        for proposal in proposals:
            print_summary(proposal)
        return 0

    if args.command == "show":
        proposal = get_proposal(paths, args.proposal_id)
        print(json.dumps(proposal, indent=2))
        return 0

    status = {"accept": "accepted", "reject": "rejected", "defer": "deferred"}[args.command]
    proposal = review_proposal(
        paths,
        proposal_id=args.proposal_id,
        status=status,
        reviewer=args.reviewer,
        note=args.note,
    )
    print(f"{status.title()} {proposal.get('proposal_id')} by {args.reviewer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
