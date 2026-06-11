from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


VALID_STATUSES = {"proposed", "accepted", "rejected", "deferred", "applied", "superseded"}
OPEN_STATUSES = {"proposed", "deferred"}


def proposal_file_path(output_dir: Path, proposal_id: str) -> Path:
    return output_dir / f"{proposal_id}.json"


def proposal_identity_fields(proposal: dict[str, Any]) -> dict[str, str]:
    kind = str(proposal.get("type") or proposal.get("kind") or "proposal")
    classification = str(
        proposal.get("classification")
        or proposal.get("source_classification")
        or ""
    )
    signature = str(proposal.get("signature") or "")
    if not signature and kind == "classification_rule":
        signature = str(proposal.get("target_classification") or "")
    elif not signature and kind == "priority_threshold":
        signature = str(proposal.get("priority") or "")
    return {
        "kind": kind,
        "source": str(proposal.get("source") or ""),
        "project": str(proposal.get("project") or ""),
        "classification": classification,
        "signature": signature,
    }


def proposal_identity_key(proposal: dict[str, Any]) -> str:
    identity = proposal_identity_fields(proposal)
    return "|".join(
        identity.get(key, "")
        for key in ("kind", "source", "project", "classification", "signature")
    )


def normalize_proposal_doc(proposal: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(proposal)
    normalized["proposal_id"] = str(normalized.get("proposal_id") or "")
    normalized["type"] = str(normalized.get("type") or normalized.get("kind") or "proposal")

    status = str(normalized.get("status") or "proposed")
    normalized["status"] = status if status in VALID_STATUSES else "proposed"
    normalized["identity"] = proposal_identity_fields(normalized)

    decision = normalized.get("decision")
    normalized["decision"] = dict(decision) if isinstance(decision, dict) else None

    applied = normalized.get("applied")
    normalized["applied"] = dict(applied) if isinstance(applied, dict) else None

    superseded_by = normalized.get("superseded_by")
    normalized["superseded_by"] = str(superseded_by or "") or None

    supersedes = normalized.get("supersedes")
    normalized["supersedes"] = str(supersedes or "") or None

    generated_at = normalized.get("generated_at")
    normalized["generated_at"] = str(generated_at or "")
    return normalized


def write_proposal_file(output_dir: Path, proposal: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized = normalize_proposal_doc(proposal)
    path = proposal_file_path(output_dir, normalized["proposal_id"])
    path.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
    return path


def load_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def load_proposal_file(path: Path) -> dict[str, Any] | None:
    payload = load_json_file(path)
    if payload is None:
        return None
    normalized = normalize_proposal_doc(payload)
    normalized["_path"] = str(path)
    return normalized


def iter_proposal_files(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted(
        [
            path for path in output_dir.glob("*.json")
            if path.name != "latest.json" and not path.name.startswith("proposals-")
        ],
        reverse=True,
    )


def load_all_proposal_files(output_dir: Path) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for path in iter_proposal_files(output_dir):
        proposal = load_proposal_file(path)
        if proposal is not None:
            proposals.append(proposal)
    return proposals


def write_latest_manifest(output_dir: Path, proposal_ids: list[str], generated_at: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": generated_at,
        "proposal_ids": proposal_ids,
    }
    manifest_path = output_dir / "latest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def load_legacy_bundle_files(output_dir: Path) -> list[dict[str, Any]]:
    if not output_dir.exists():
        return []

    runs: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("proposals-*.json"), reverse=True):
        payload = load_json_file(path)
        if payload is None:
            continue
        payload["_path"] = str(path)
        runs.append(payload)
    return runs


def build_runs_from_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposal in proposals:
        grouped[str(proposal.get("generated_at") or "")].append(proposal)

    runs: list[dict[str, Any]] = []
    for generated_at, group in grouped.items():
        ordered = sorted(
            group,
            key=lambda proposal: str(proposal.get("proposal_id") or ""),
            reverse=True,
        )
        runs.append(
            {
                "generated_at": generated_at,
                "proposal_count": len(ordered),
                "proposal_ids": [str(item.get("proposal_id") or "") for item in ordered],
                "proposals": ordered,
            }
        )

    runs.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
    return runs
