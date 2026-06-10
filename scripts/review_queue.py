#!/usr/bin/env python3
"""Manual review CLI for pending alerts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alert_agent.core.manual_review import ACTION_TO_QUEUE, dispatch_approved, ensure_dirs, find_issue, issue_summary, list_issues, load_issue, load_paths, record_action


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/agent_config.yaml", help="Config file path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List issues in a review queue")
    list_parser.add_argument("--status", choices=["approved", "ignored", "pending", "rejected"], default="pending")
    list_parser.add_argument("--limit", type=int, default=20)
    list_parser.add_argument("--json", action="store_true", help="Print JSON instead of text")

    show_parser = subparsers.add_parser("show", help="Show one issue from a review queue")
    show_parser.add_argument("issue_id", help="Issue ID, with or without .json")
    show_parser.add_argument("--status", choices=["approved", "ignored", "pending", "rejected"], default=None)
    show_parser.add_argument("--json", action="store_true", help="Print full JSON")

    for action in ("approve", "reject", "ignore"):
        action_parser = subparsers.add_parser(action, help=f"{action.title()} one pending issue")
        action_parser.add_argument("issue_id", help="Pending issue ID, with or without .json")
        action_parser.add_argument("--reviewer", default="manual", help="Reviewer name for the audit log")
        action_parser.add_argument("--note", default="", help="Decision note")
        action_parser.add_argument("--priority", choices=["P0", "P1", "P2", "P3"], help="Override final priority")
        action_parser.add_argument("--classification", dest="classification", help="Override final class")
        action_parser.add_argument("--danger", choices=["critical", "high", "medium", "low"], help="Override danger")

    dispatch_parser = subparsers.add_parser("dispatch", help="Run recommendation and optionally sender for approved issues")
    dispatch_parser.add_argument("--dry-run", action="store_true", help="Run recommendation fallback mode and sender dry-run")
    dispatch_parser.add_argument("--send", action="store_true", help="Send to Teams for real; default is sender dry-run")

    return parser.parse_args()


def print_issue_text(summary: dict[str, object]) -> None:
    print(
        f"{summary['issue_id']}: {summary['priority']} {summary['classification']} "
        f"[{summary['status']}] team={summary['review_team']} project={summary['project']} "
        f"count={summary['count']} users={summary['users']} decision={summary['review_decision']} "
        f"confidence={summary['review_confidence']}"
    )


def command_list(args: argparse.Namespace, paths: dict[str, Path]) -> int:
    summaries = list_issues(paths, args.status, limit=max(args.limit, 0))
    if args.json:
        print(json.dumps(summaries, indent=2))
        return 0

    if not summaries:
        print(f"No issues in {args.status}")
        return 0

    for summary in summaries:
        print_issue_text(summary)
    return 0


def command_show(args: argparse.Namespace, paths: dict[str, Path]) -> int:
    status, path = find_issue(paths, args.issue_id, args.status)
    issue = load_issue(path)

    if args.json:
        print(json.dumps(issue, indent=2))
        return 0

    summary = issue_summary(issue, status)
    print_issue_text(summary)
    print("")
    print(f"Path: {path}")
    print(f"Link: {issue.get('metadata', {}).get('link', '')}")
    print(f"Reasoning: {issue.get('review', {}).get('reasoning', '')}")
    manual_note = issue.get("manual_review", {}).get("note")
    if manual_note:
        print(f"Manual note: {manual_note}")
    return 0


def command_action(args: argparse.Namespace, paths: dict[str, Path]) -> int:
    result = record_action(
        paths,
        issue_id=args.issue_id,
        action=str(args.command),
        reviewer=args.reviewer,
        note=args.note,
        priority=getattr(args, "priority", None),
        classification=getattr(args, "classification", None),
        danger=getattr(args, "danger", None),
    )
    print(f"{str(args.command).title()}d {result['issue'].get('issue_id')} -> {result['target_status']}")
    if args.note:
        print(f"Note: {args.note}")
    return 0


def command_dispatch(args: argparse.Namespace, paths: dict[str, Path], config_file: str) -> int:
    approved_summaries = list_issues(paths, "approved", limit=1)
    if not approved_summaries:
        print("No approved issues to dispatch")
        return 0
    return dispatch_approved(paths, config_file, dry_run=args.dry_run, send=args.send)


def main() -> int:
    args = parse_args()
    paths = load_paths(args.config)
    ensure_dirs(paths)

    if args.command == "list":
        return command_list(args, paths)
    if args.command == "show":
        return command_show(args, paths)
    if args.command in ACTION_TO_QUEUE:
        return command_action(args, paths)
    if args.command == "dispatch":
        return command_dispatch(args, paths, args.config)
    raise ValueError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
