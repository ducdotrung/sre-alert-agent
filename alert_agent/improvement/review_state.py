from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from alert_agent.improvement.decisions import record_proposal_decision
from alert_agent.improvement.storage import (
    VALID_STATUSES,
    build_runs_from_proposals,
    load_all_proposal_files,
    load_legacy_bundle_files,
    load_proposal_file,
    proposal_file_path,
)


def proposals_dir(paths: dict[str, Path]) -> Path:
    return paths["output_dir"] / "improvement" / "proposals"


def review_state_path(paths: dict[str, Path]) -> Path:
    return paths["metrics_dir"] / "improvement_review_state.json"


def review_audit_path(paths: dict[str, Path]) -> Path:
    return paths["metrics_dir"] / "improvement_review_actions.jsonl"


def load_review_state(paths: dict[str, Path]) -> dict[str, dict[str, Any]]:
    path = review_state_path(paths)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key): dict(value) for key, value in payload.items() if isinstance(value, dict)}


def save_review_state(paths: dict[str, Path], state: dict[str, dict[str, Any]]) -> None:
    path = review_state_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_review_audit(paths: dict[str, Path], event: dict[str, Any]) -> None:
    path = review_audit_path(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=True) + "\n")


def load_improvement_runs(paths: dict[str, Path]) -> list[dict[str, Any]]:
    directory = proposals_dir(paths)
    runs = build_runs_from_proposals(load_all_proposal_files(directory))
    runs.extend(load_legacy_bundle_files(directory))
    runs.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    return runs


def flatten_proposals(
    runs: list[dict[str, Any]],
    review_state: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    state = review_state or {}
    flattened: list[dict[str, Any]] = []
    seen: set[str] = set()

    for run in runs:
        generated_at = str(run.get("generated_at") or "")
        source_path = str(run.get("_path") or "")
        proposals = run.get("proposals", [])
        if not isinstance(proposals, list):
            continue

        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            proposal_id = str(proposal.get("proposal_id") or "")
            if not proposal_id or proposal_id in seen:
                continue

            merged = dict(proposal)
            merged["_generated_at"] = generated_at
            merged["_bundle_path"] = source_path

            review = state.get(proposal_id)
            if isinstance(merged.get("decision"), dict):
                decision = dict(merged["decision"])
                merged["status"] = decision.get("status", merged.get("status", "proposed"))
                merged["reviewer"] = decision.get("reviewer", "")
                merged["review_note"] = decision.get("note", "")
                merged["reviewed_at"] = decision.get("timestamp", "")
            elif review:
                merged["status"] = review.get("status", merged.get("status", "proposed"))
                merged["reviewer"] = review.get("reviewer", "")
                merged["review_note"] = review.get("note", "")
                merged["reviewed_at"] = review.get("timestamp", "")

            if str(merged.get("status") or "") not in VALID_STATUSES:
                merged["status"] = "proposed"

            flattened.append(merged)
            seen.add(proposal_id)

    flattened.sort(
        key=lambda proposal: (
            str(proposal.get("_generated_at") or ""),
            str(proposal.get("proposal_id") or ""),
        ),
        reverse=True,
    )
    return flattened


def get_proposal(paths: dict[str, Path], proposal_id: str) -> dict[str, Any]:
    proposal_path = proposal_file_path(proposals_dir(paths), proposal_id)
    if proposal_path.exists():
        proposal = load_proposal_file(proposal_path)
        if proposal is not None:
            flattened = flatten_proposals(build_runs_from_proposals([proposal]), load_review_state(paths))
            if flattened:
                return flattened[0]

    runs = load_improvement_runs(paths)
    proposals = flatten_proposals(runs, load_review_state(paths))
    for proposal in proposals:
        if str(proposal.get("proposal_id") or "") == proposal_id:
            return proposal
    raise FileNotFoundError(f"Proposal not found: {proposal_id}")


def review_proposal(
    paths: dict[str, Path],
    *,
    proposal_id: str,
    status: str,
    reviewer: str,
    note: str = "",
) -> dict[str, Any]:
    normalized_status = str(status).strip().lower()
    if normalized_status not in {"accepted", "rejected", "deferred"}:
        raise ValueError(f"Unsupported proposal status: {status}")
    updated = record_proposal_decision(
        paths,
        proposal_id=proposal_id,
        status=normalized_status,
        reviewer=reviewer,
        note=note,
    )

    # Keep compatibility files current while the older review UI/tests still read them.
    proposal = get_proposal(paths, proposal_id)
    state = load_review_state(paths)
    timestamp = str(updated.get("reviewed_at") or dt.datetime.now(dt.timezone.utc).isoformat())
    state[proposal_id] = {
        "status": normalized_status,
        "reviewer": reviewer,
        "note": note,
        "timestamp": timestamp,
        "type": proposal.get("type"),
        "source": proposal.get("source"),
        "project": proposal.get("project"),
        "policy_pack": proposal.get("policy_pack"),
    }
    save_review_state(paths, state)
    append_review_audit(
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
