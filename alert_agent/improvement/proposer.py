from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from alert_agent.core.ai_client import PiAIClient, format_prompt, load_prompt_template


TARGET_FILES = {
    "ignore_rule": ["config/ignore_rules.json"],
    "classification_rule": ["config/classification_rules.yaml"],
    "priority_threshold": ["config/priority_thresholds.yaml"],
    "prompt_improvement": ["prompts/review_decision.md", "prompts/triage_reclassify.md"],
}


def _risk_for_kind(kind: str) -> str:
    return {
        "ignore_rule": "low",
        "classification_rule": "medium",
        "priority_threshold": "medium",
        "prompt_improvement": "medium",
    }.get(kind, "medium")


def _base_summary(pattern: dict[str, Any]) -> str:
    kind = str(pattern.get("kind") or "")
    source = str(pattern.get("source") or "unknown")
    project = str(pattern.get("project") or "unknown")
    sample_size = int(pattern.get("sample_size") or 0)
    if kind == "ignore_rule":
        return f"Suggest ignore/noise suppression review for {source} {project} {pattern.get('classification')} pattern ({sample_size} cases)."
    if kind == "classification_rule":
        return f"Suggest classification tuning for {source} {project}: {pattern.get('source_classification')} -> {pattern.get('target_classification')} ({sample_size} cases)."
    if kind == "priority_threshold":
        return f"Suggest priority tuning for {source} {project} {pattern.get('classification')} currently landing as {pattern.get('priority')} ({sample_size} cases)."
    return f"Suggest review prompt improvement for {source} {project} {pattern.get('classification')} based on reviewer notes ({sample_size} cases)."


def _suggested_change(pattern: dict[str, Any]) -> dict[str, Any]:
    kind = str(pattern.get("kind") or "")
    if kind == "ignore_rule":
        case = pattern["cases"][0]
        return {
            "rule_hint": {
                "source": case.get("source"),
                "project": case.get("project"),
                "class": case.get("classification"),
                "title_contains": case.get("title_signature"),
            }
        }
    if kind == "classification_rule":
        return {
            "rule_hint": {
                "source": pattern.get("source"),
                "project": pattern.get("project"),
                "from": pattern.get("source_classification"),
                "to": pattern.get("target_classification"),
            }
        }
    if kind == "priority_threshold":
        return {
            "threshold_hint": {
                "source": pattern.get("source"),
                "project": pattern.get("project"),
                "class": pattern.get("classification"),
                "priority": pattern.get("priority"),
                "review_outcome_bias": pattern.get("evidence_counts"),
            }
        }
    return {
        "prompt_hint": {
            "source": pattern.get("source"),
            "project": pattern.get("project"),
            "class": pattern.get("classification"),
            "note_examples": pattern.get("notes", [])[:5],
        }
    }


def _proposal_confidence(pattern: dict[str, Any]) -> float:
    sample_size = max(int(pattern.get("sample_size") or 0), 1)
    return min(0.55 + (sample_size * 0.08), 0.95)


def summarize_pattern_with_ai(pattern: dict[str, Any], ai_client: PiAIClient | None) -> str:
    """Use AI to create a short proposal summary, with fallback."""
    if ai_client is None:
        return _base_summary(pattern)

    notes = pattern.get("notes", [])[:8]
    template = load_prompt_template("self_improve_summarize.md")
    prompt = format_prompt(
        template,
        pattern_kind=pattern.get("kind"),
        source=pattern.get("source"),
        project=pattern.get("project"),
        classification=pattern.get("classification"),
        priority=pattern.get("priority"),
        sample_size=pattern.get("sample_size"),
        evidence_counts=json.dumps(pattern.get("evidence_counts", {}), ensure_ascii=True),
        reviewer_notes=json.dumps(notes, ensure_ascii=True),
    )
    try:
        return ai_client.query(
            prompt,
            metadata={
                "operation": "self_improve_summarize",
                "pattern_kind": pattern.get("kind"),
                "source": pattern.get("source"),
                "project": pattern.get("project"),
            },
        ).strip()
    except Exception:
        return _base_summary(pattern)


def build_proposals(patterns: list[dict[str, Any]], ai_client: PiAIClient | None = None) -> list[dict[str, Any]]:
    """Turn analyzed patterns into proposal documents."""
    proposals: list[dict[str, Any]] = []
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    for index, pattern in enumerate(patterns, start=1):
        kind = str(pattern.get("kind") or "proposal")
        proposal = {
            "proposal_id": f"{kind}-{stamp}-{index:03d}",
            "type": kind,
            "status": "proposed",
            "summary": summarize_pattern_with_ai(pattern, ai_client),
            "confidence": round(_proposal_confidence(pattern), 2),
            "risk": _risk_for_kind(kind),
            "evidence": {
                "sample_size": int(pattern.get("sample_size") or 0),
                "manual_actions": pattern.get("evidence_counts", {}),
                "notes": pattern.get("notes", [])[:8],
            },
            "source": pattern.get("source"),
            "project": pattern.get("project"),
            "policy_pack": pattern.get("policy_pack"),
            "classification": pattern.get("classification"),
            "priority": pattern.get("priority"),
            "target_files": TARGET_FILES.get(kind, []),
            "suggested_change": _suggested_change(pattern),
            "related_issue_ids": pattern.get("related_issue_ids", []),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        proposals.append(proposal)
    return proposals


def write_proposal_bundle(output_dir: Path, proposals: list[dict[str, Any]]) -> Path:
    """Write one proposal bundle and refresh latest.json."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bundle = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "proposal_count": len(proposals),
        "proposals": proposals,
    }
    bundle_path = output_dir / f"proposals-{timestamp}.json"
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    latest_path = output_dir / "latest.json"
    latest_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle_path
