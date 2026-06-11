from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from alert_agent.improvement.storage import write_proposal_file


DECISION_STATUSES = {"accepted", "rejected", "deferred"}


def proposal_decisions_path(paths: dict[str, Path]) -> Path:
    return paths["metrics_dir"] / "proposal_decisions.jsonl"


def proposals_dir(paths: dict[str, Path]) -> Path:
    return paths["output_dir"] / "improvement" / "proposals"


def append_proposal_decision(paths: dict[str, Path], event: dict[str, Any]) -> None:
    path = proposal_decisions_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def record_proposal_decision(
    paths: dict[str, Path],
    *,
    proposal_id: str,
    status: str,
    reviewer: str,
    note: str = "",
) -> dict[str, Any]:
    from alert_agent.improvement.review_state import get_proposal

    normalized_status = str(status).strip().lower()
    if normalized_status not in DECISION_STATUSES:
        raise ValueError(f"Unsupported proposal status: {status}")

    proposal = get_proposal(paths, proposal_id)
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    decision = {
        "status": normalized_status,
        "reviewer": reviewer,
        "note": note,
        "timestamp": timestamp,
    }

    updated = dict(proposal)
    updated["status"] = normalized_status
    updated["decision"] = decision
    updated["reviewer"] = reviewer
    updated["review_note"] = note
    updated["reviewed_at"] = timestamp

    write_proposal_file(proposals_dir(paths), updated)
    append_proposal_decision(
        paths,
        {
            "timestamp": timestamp,
            "proposal_id": proposal_id,
            "status": normalized_status,
            "reviewer": reviewer,
            "note": note,
            "type": proposal.get("type"),
            "source": proposal.get("source"),
            "project": proposal.get("project"),
            "policy_pack": proposal.get("policy_pack"),
        },
    )
    return updated


def record_proposal_applied(
    paths: dict[str, Path],
    *,
    proposal_id: str,
    commit_sha: str,
) -> dict[str, Any]:
    from alert_agent.improvement.review_state import get_proposal

    proposal = get_proposal(paths, proposal_id)
    status = str(proposal.get("status") or "proposed")
    if status not in {"accepted", "applied"}:
        raise ValueError(f"Apply requires an accepted proposal, got {status}")

    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    patch_artifact = proposal.get("patch_artifact", {})
    applied = {
        "timestamp": timestamp,
        "commit_sha": commit_sha,
        "target_file": str(patch_artifact.get("target_file") or ""),
        "change_summary": str(proposal.get("summary") or ""),
    }
    updated = dict(proposal)
    updated["status"] = "applied"
    updated["applied"] = applied
    write_proposal_file(proposals_dir(paths), updated)
    append_proposal_decision(
        paths,
        {
            "timestamp": timestamp,
            "proposal_id": proposal_id,
            "status": "applied",
            "commit_sha": commit_sha,
            "type": proposal.get("type"),
            "source": proposal.get("source"),
            "project": proposal.get("project"),
            "policy_pack": proposal.get("policy_pack"),
        },
    )
    return updated
