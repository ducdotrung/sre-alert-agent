from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from pathlib import Path
from typing import Any

import yaml

from alert_agent.commands.run_self_improve import build_ai_client
from alert_agent.core.config_loader import load_agent_config
from alert_agent.improvement.review_state import get_proposal
from alert_agent.improvement.storage import write_proposal_file


def patches_dir(paths: dict[str, Path]) -> Path:
    return paths["output_dir"] / "improvement" / "patches"


def patch_path(paths: dict[str, Path], proposal_id: str) -> Path:
    return patches_dir(paths) / f"{proposal_id}.patch"


def _repo_file(paths: dict[str, Path], relative_path: str) -> Path:
    return paths["repo_root"] / relative_path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_patch(old_text: str, new_text: str, relative_path: str) -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(),
        new_text.splitlines(),
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
        lineterm="",
    )
    return "\n".join(diff) + "\n"


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return cleaned.strip("-") or "rule"


def _ignore_rule_doc(proposal: dict[str, Any]) -> tuple[str, str]:
    relative_path = "config/ignore_rules.json"
    target_path = relative_path
    payload = json.loads(_read_text(_repo_file(proposal["_paths"], relative_path)))
    rules = list(payload.get("rules") or [])
    hint = dict(proposal.get("suggested_change", {}).get("rule_hint", {}))
    identity = proposal.get("identity", {})
    sample_size = int(proposal.get("evidence", {}).get("sample_size") or 0)
    rule_id = "ignore-" + "-".join(
        part for part in [
            _slugify(str(identity.get("source") or "")),
            _slugify(str(identity.get("project") or "")),
            _slugify(str(identity.get("classification") or "")),
            _slugify(str(identity.get("signature") or hint.get("title_contains") or "")),
        ] if part
    )
    if any(str(item.get("id") or "") == rule_id for item in rules):
        new_payload = payload
    else:
        new_rule = {
            "id": rule_id,
            "enabled": True,
            "class": hint.get("class") or identity.get("classification"),
            "title_contains": hint.get("title_contains") or identity.get("signature"),
            "reason": str(proposal.get("summary") or "Self-improvement suggested ignore rule"),
            "max_count": max(sample_size * 2, 25),
            "expires": (dt.date.today() + dt.timedelta(days=180)).isoformat(),
            "added_by": "self-improve",
            "added_date": dt.date.today().isoformat(),
        }
        if hint.get("project"):
            new_rule["project"] = hint["project"]
        new_payload = dict(payload)
        new_payload["rules"] = rules + [new_rule]
    old_text = json.dumps(payload, indent=2)
    new_text = json.dumps(new_payload, indent=2)
    return target_path, _write_patch(old_text, new_text, relative_path)


def _classification_rule_doc(proposal: dict[str, Any]) -> tuple[str, str]:
    relative_path = "config/classification_rules.yaml"
    payload = yaml.safe_load(_read_text(_repo_file(proposal["_paths"], relative_path))) or {}
    classes = dict(payload.get("classes") or {})
    target_class = str(proposal.get("target_classification") or proposal.get("classification") or "")
    hint = dict(proposal.get("suggested_change", {}).get("rule_hint", {}))
    keyword = str(hint.get("keyword") or proposal.get("signature") or "").strip()
    class_doc = dict(classes.get(target_class) or {})
    keywords = list(class_doc.get("keywords") or [])
    if keyword and keyword not in keywords:
        keywords.append(keyword)
        keywords.sort()
    class_doc["keywords"] = keywords
    if "priority" not in class_doc:
        class_doc["priority"] = "medium"
    classes[target_class] = class_doc
    new_payload = dict(payload)
    new_payload["classes"] = classes
    old_text = yaml.safe_dump(payload, sort_keys=False)
    new_text = yaml.safe_dump(new_payload, sort_keys=False)
    return relative_path, _write_patch(old_text, new_text, relative_path)


def _priority_threshold_doc(proposal: dict[str, Any]) -> tuple[str, str]:
    relative_path = "config/priority_thresholds.yaml"
    payload = yaml.safe_load(_read_text(_repo_file(proposal["_paths"], relative_path))) or {}
    thresholds = dict(payload.get("class_thresholds") or {})
    classification = str(proposal.get("classification") or "")
    priority = str(proposal.get("priority") or "P1")
    class_doc = dict(thresholds.get(classification) or {})
    level_doc = dict(class_doc.get(priority) or {"count": 100, "users": 10})
    count = int(level_doc.get("count") or 0)
    users = int(level_doc.get("users") or 0)
    level_doc["count"] = max(int(round(count * 0.8)), 1) if count > 0 else 1
    level_doc["users"] = max(int(round(users * 0.8)), 0)
    class_doc[priority] = level_doc
    thresholds[classification] = class_doc
    new_payload = dict(payload)
    new_payload["class_thresholds"] = thresholds
    old_text = yaml.safe_dump(payload, sort_keys=False)
    new_text = yaml.safe_dump(new_payload, sort_keys=False)
    return relative_path, _write_patch(old_text, new_text, relative_path)


def _fallback_prompt_patch(old_text: str, proposal: dict[str, Any]) -> str:
    notes = [str(item).strip() for item in proposal.get("evidence", {}).get("notes", []) if str(item).strip()]
    addition_lines = ["", "## Examples Reviewers Rejected", ""]
    for note in notes[:5]:
        addition_lines.append(f"- {note}")
    if len(addition_lines) == 3:
        addition_lines.append("- No reviewer notes were captured.")
    return old_text.rstrip() + "\n" + "\n".join(addition_lines) + "\n"


def _prompt_improvement_doc(proposal: dict[str, Any], config_file: str) -> tuple[str, str]:
    relative_path = "prompts/review_decision.md"
    target = _repo_file(proposal["_paths"], relative_path)
    old_text = _read_text(target)
    new_text = old_text

    try:
        config = load_agent_config("self_improve", config_file)
        ai_client = build_ai_client(config)
    except Exception:
        ai_client = None

    if ai_client is not None:
        prompt = (
            "Return a unified diff patch only.\n"
            f"File: {relative_path}\n\n"
            "Current file:\n"
            f"{old_text}\n\n"
            "Reviewer notes:\n"
            f"{json.dumps(proposal.get('evidence', {}).get('notes', []), ensure_ascii=True, indent=2)}\n"
        )
        try:
            ai_diff = ai_client.query(prompt, metadata={"operation": "self_improve_patch", "proposal_id": proposal.get("proposal_id")})
            if ai_diff.strip().startswith("--- "):
                return relative_path, ai_diff if ai_diff.endswith("\n") else ai_diff + "\n"
        except Exception:
            pass

    new_text = _fallback_prompt_patch(old_text, proposal)
    return relative_path, _write_patch(old_text, new_text, relative_path)


def generate_patch_for_proposal(
    paths: dict[str, Path],
    proposal_id: str,
    *,
    config_file: str = "config/agent_config.yaml",
) -> Path:
    proposal = get_proposal(paths, proposal_id)
    status = str(proposal.get("status") or "proposed")
    if status not in {"accepted", "applied"}:
        raise ValueError(f"Patch generation requires an accepted proposal, got {status}")

    proposal["_paths"] = paths
    proposal_type = str(proposal.get("type") or "")
    if proposal_type == "ignore_rule":
        target_file, patch_text = _ignore_rule_doc(proposal)
    elif proposal_type == "classification_rule":
        target_file, patch_text = _classification_rule_doc(proposal)
    elif proposal_type == "priority_threshold":
        target_file, patch_text = _priority_threshold_doc(proposal)
    elif proposal_type == "prompt_improvement":
        target_file, patch_text = _prompt_improvement_doc(proposal, config_file)
    else:
        raise ValueError(f"Unsupported proposal type for patch generation: {proposal_type}")

    destination = patch_path(paths, proposal_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(patch_text, encoding="utf-8")

    updated = dict(proposal)
    updated["patch_artifact"] = {
        "path": str(destination),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target_file": target_file,
    }
    updated.pop("_paths", None)
    write_proposal_file(paths["output_dir"] / "improvement" / "proposals", updated)
    return destination
