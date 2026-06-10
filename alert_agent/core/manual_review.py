"""Shared manual review queue helpers for CLI and web workflows."""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config_loader import get_repo_root, load_agent_config


QUEUE_DIRS = {
    "pending": "pending",
    "approved": "approved",
    "rejected": "rejected",
    "ignored": "ignored",
}

ACTION_TO_QUEUE = {
    "approve": "approved",
    "reject": "rejected",
    "ignore": "ignored",
}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_paths(config_file: str) -> dict[str, Path]:
    common_config = load_agent_config("common", config_file)
    output_dir = Path(common_config.get("output_dir", "./output"))
    metrics_dir = Path(common_config.get("metrics_dir", "./output/metrics"))
    alerts_dir = output_dir / "alerts"
    return {
        "repo_root": get_repo_root(),
        "output_dir": output_dir,
        "alerts_dir": alerts_dir,
        "metrics_dir": metrics_dir,
        "audit_log": metrics_dir / "manual_review_actions.jsonl",
    }


def queue_path(paths: dict[str, Path], status: str) -> Path:
    return paths["alerts_dir"] / QUEUE_DIRS[status]


def ensure_dirs(paths: dict[str, Path]) -> None:
    for status in QUEUE_DIRS:
        queue_path(paths, status).mkdir(parents=True, exist_ok=True)
    paths["metrics_dir"].mkdir(parents=True, exist_ok=True)


def issue_filename(issue_id: str) -> str:
    return issue_id if issue_id.endswith(".json") else f"{issue_id}.json"


def find_issue(paths: dict[str, Path], issue_id: str, status: str | None) -> tuple[str, Path]:
    filename = issue_filename(issue_id)
    if status is not None:
        candidate = queue_path(paths, status) / filename
        if candidate.exists():
            return status, candidate
        raise FileNotFoundError(f"{issue_id} not found in {status}")

    for candidate_status in ("pending", "approved", "rejected", "ignored"):
        candidate = queue_path(paths, candidate_status) / filename
        if candidate.exists():
            return candidate_status, candidate

    raise FileNotFoundError(f"{issue_id} not found in any review queue")


def load_issue(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def classify_review_team(project: str | None) -> str:
    if not project:
        return "unassigned"
    lowered = project.lower()
    if "ai" in lowered:
        return "ai-team"
    if "backend" in lowered or "api" in lowered:
        return "backend-team"
    return "developer-team"


def issue_summary(issue: dict[str, Any], status: str) -> dict[str, Any]:
    review = issue.get("review", {})
    final = issue.get("final", {})
    metadata = issue.get("metadata", {})
    manual_review = issue.get("manual_review", {})
    project = metadata.get("project")
    return {
        "issue_id": issue.get("issue_id"),
        "alert_id": issue.get("alert_id"),
        "source": issue.get("source"),
        "policy_pack": issue.get("policy_pack"),
        "status": status,
        "priority": final.get("priority"),
        "classification": final.get("class"),
        "danger": final.get("danger"),
        "project": project,
        "review_team": classify_review_team(project),
        "title": metadata.get("title"),
        "count": metadata.get("count"),
        "users": metadata.get("users"),
        "review_decision": review.get("decision"),
        "review_confidence": review.get("confidence"),
        "last_seen": metadata.get("last_seen"),
        "manual_action": manual_review.get("action"),
        "manual_reviewer": manual_review.get("reviewer"),
        "link": metadata.get("link"),
    }


def append_audit_log(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def list_issues(
    paths: dict[str, Path],
    status: str,
    limit: int = 20,
    project: str | None = None,
    priority: str | None = None,
    team: str | None = None,
) -> list[dict[str, Any]]:
    target_dir = queue_path(paths, status)
    files = sorted(target_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    summaries: list[dict[str, Any]] = []

    for path in files:
        summary = issue_summary(load_issue(path), status)
        if project and summary.get("project") != project:
            continue
        if priority and summary.get("priority") != priority:
            continue
        if team and summary.get("review_team") != team:
            continue
        summaries.append(summary)
        if limit > 0 and len(summaries) >= limit:
            break

    return summaries


def apply_overrides(
    issue: dict[str, Any],
    *,
    priority: str | None = None,
    classification: str | None = None,
    danger: str | None = None,
) -> dict[str, Any]:
    final = issue.setdefault("final", {})
    overrides: dict[str, Any] = {}

    if priority:
        final["priority"] = priority
        overrides["priority"] = priority
    if classification:
        final["class"] = classification
        overrides["classification"] = classification
    if danger:
        final["danger"] = danger
        overrides["danger"] = danger

    return overrides


def record_action(
    paths: dict[str, Path],
    *,
    issue_id: str,
    action: str,
    reviewer: str,
    note: str = "",
    priority: str | None = None,
    classification: str | None = None,
    danger: str | None = None,
) -> dict[str, Any]:
    if action not in ACTION_TO_QUEUE:
        raise ValueError(f"Unsupported action: {action}")

    source_status, source_path = find_issue(paths, issue_id, "pending")
    issue = load_issue(source_path)
    target_status = ACTION_TO_QUEUE[action]
    target_path = queue_path(paths, target_status) / source_path.name

    if target_path.exists():
        raise FileExistsError(f"Target already exists: {target_path}")

    overrides = apply_overrides(
        issue,
        priority=priority,
        classification=classification,
        danger=danger,
    )
    timestamp = now_utc()

    review = issue.setdefault("review", {})
    previous_review_decision = review.get("decision")
    if action == "approve":
        review["decision"] = "send"
    elif action == "reject":
        review["decision"] = "hold"
    elif action == "ignore":
        review["decision"] = "ignore"
    review["manual_override"] = True

    history_entry = {
        "timestamp": timestamp,
        "action": action,
        "reviewer": reviewer,
        "note": note,
        "source_status": source_status,
        "target_status": target_status,
        "previous_review_decision": previous_review_decision,
        "overrides": overrides,
    }

    issue["manual_review"] = {
        "action": action,
        "reviewer": reviewer,
        "note": note,
        "timestamp": timestamp,
        "source_status": source_status,
        "target_status": target_status,
        "overrides": overrides,
    }
    issue.setdefault("manual_review_history", []).append(history_entry)

    target_path.write_text(json.dumps(issue, indent=2), encoding="utf-8")
    source_path.unlink()

    audit_event = {
        "timestamp": timestamp,
        "issue_id": issue.get("issue_id"),
        "alert_id": issue.get("alert_id"),
        "source": issue.get("source"),
        "policy_pack": issue.get("policy_pack"),
        "sentry_id": issue.get("sentry_id"),
        "action": action,
        "reviewer": reviewer,
        "note": note,
        "source_status": source_status,
        "target_status": target_status,
        "priority": issue.get("final", {}).get("priority"),
        "classification": issue.get("final", {}).get("class"),
        "danger": issue.get("final", {}).get("danger"),
        "project": issue.get("metadata", {}).get("project"),
        "review_team": classify_review_team(issue.get("metadata", {}).get("project")),
        "previous_review_decision": previous_review_decision,
        "updated_review_decision": review.get("decision"),
        "overrides": overrides,
        "source_path": str(source_path),
        "target_path": str(target_path),
    }
    append_audit_log(paths["audit_log"], audit_event)

    return {
        "issue": issue,
        "action": action,
        "source_status": source_status,
        "target_status": target_status,
        "target_path": target_path,
        "audit_event": audit_event,
    }


def run_command(command: list[str], cwd: Path) -> int:
    result = subprocess.run(command, cwd=cwd, check=False)
    return int(result.returncode)


def dispatch_approved(paths: dict[str, Path], config_file: str, *, dry_run: bool, send: bool) -> int:
    repo_root = paths["repo_root"]
    approved_count = len(list(queue_path(paths, "approved").glob("*.json")))
    if approved_count == 0:
        return 0

    recommendation_command = [sys.executable, "agents/recommendation_agent.py", "--config", config_file]
    if dry_run:
        recommendation_command.append("--dry-run")
    recommendation_exit = run_command(recommendation_command, repo_root)
    if recommendation_exit not in (0, 2):
        return recommendation_exit

    sender_command = [sys.executable, "agents/sender.py", "--config", config_file]
    if dry_run or not send:
        sender_command.append("--dry-run")
    return run_command(sender_command, repo_root)


def recent_audit_events(paths: dict[str, Path], limit: int = 20) -> list[dict[str, Any]]:
    audit_path = paths["audit_log"]
    if not audit_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for line in audit_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return list(reversed(events[-limit:]))
