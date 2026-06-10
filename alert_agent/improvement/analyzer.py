from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _evidence_counts(cases: list[dict[str, Any]]) -> dict[str, int]:
    action_counts: Counter[str] = Counter()
    for case in cases:
        for event in case.get("events", []):
            action_counts[str(event.get("action") or "unknown")] += 1
    return dict(action_counts)


def find_ignore_rule_patterns(cases: list[dict[str, Any]], min_cases: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        events = case.get("events", [])
        final_action = str(events[-1].get("action") or "") if events else ""
        if final_action not in {"ignore", "reject"}:
            continue
        key = (
            str(case.get("source") or ""),
            str(case.get("project") or ""),
            str(case.get("classification") or ""),
            str(case.get("title_signature") or ""),
        )
        groups[key].append(case)

    patterns: list[dict[str, Any]] = []
    for key, group in groups.items():
        if len(group) < min_cases:
            continue
        source, project, classification, signature = key
        notes = [note for case in group for note in case.get("notes", [])]
        patterns.append(
            {
                "kind": "ignore_rule",
                "source": source,
                "project": project,
                "classification": classification,
                "signature": signature,
                "policy_pack": group[0].get("policy_pack"),
                "sample_size": len(group),
                "related_issue_ids": [case["issue_id"] for case in group[:12]],
                "notes": notes[:8],
                "cases": group,
                "evidence_counts": _evidence_counts(group),
            }
        )
    return patterns


def find_classification_override_patterns(cases: list[dict[str, Any]], min_cases: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        override_events = [
            event for event in case.get("events", [])
            if isinstance(event.get("overrides"), dict) and event["overrides"].get("classification")
        ]
        if not override_events:
            continue
        target = str(override_events[-1]["overrides"]["classification"])
        source = str(case.get("classification") or "unknown")
        key = (str(case.get("source") or ""), str(case.get("project") or ""), source, target)
        groups[key].append(case)

    patterns: list[dict[str, Any]] = []
    for key, group in groups.items():
        if len(group) < min_cases:
            continue
        source_name, project, source, target = key
        patterns.append(
            {
                "kind": "classification_rule",
                "source": source_name,
                "project": project,
                "policy_pack": group[0].get("policy_pack"),
                "source_classification": source,
                "target_classification": target,
                "sample_size": len(group),
                "related_issue_ids": [case["issue_id"] for case in group[:12]],
                "notes": [note for case in group for note in case.get("notes", [])][:8],
                "cases": group,
                "evidence_counts": _evidence_counts(group),
            }
        )
    return patterns


def find_priority_patterns(cases: list[dict[str, Any]], min_cases: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        events = case.get("events", [])
        final_action = str(events[-1].get("action") or "") if events else ""
        if final_action not in {"reject", "ignore"}:
            continue
        priority = str(case.get("priority") or "unknown")
        classification = str(case.get("classification") or "unknown")
        key = (str(case.get("source") or ""), str(case.get("project") or ""), classification, priority)
        groups[key].append(case)

    patterns: list[dict[str, Any]] = []
    for key, group in groups.items():
        if len(group) < min_cases:
            continue
        source, project, classification, priority = key
        patterns.append(
            {
                "kind": "priority_threshold",
                "source": source,
                "project": project,
                "policy_pack": group[0].get("policy_pack"),
                "classification": classification,
                "priority": priority,
                "sample_size": len(group),
                "related_issue_ids": [case["issue_id"] for case in group[:12]],
                "notes": [note for case in group for note in case.get("notes", [])][:8],
                "cases": group,
                "evidence_counts": _evidence_counts(group),
            }
        )
    return patterns


def find_prompt_patterns(cases: list[dict[str, Any]], min_cases: int) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        if not case.get("notes"):
            continue
        key = (
            str(case.get("source") or ""),
            str(case.get("project") or ""),
            str(case.get("classification") or "unknown"),
        )
        groups[key].append(case)

    patterns: list[dict[str, Any]] = []
    for key, group in groups.items():
        if len(group) < min_cases:
            continue
        source, project, classification = key
        patterns.append(
            {
                "kind": "prompt_improvement",
                "source": source,
                "project": project,
                "policy_pack": group[0].get("policy_pack"),
                "classification": classification,
                "sample_size": len(group),
                "related_issue_ids": [case["issue_id"] for case in group[:12]],
                "notes": [note for case in group for note in case.get("notes", [])][:12],
                "cases": group,
                "evidence_counts": _evidence_counts(group),
            }
        )
    return patterns


def analyze_review_cases(cases: list[dict[str, Any]], min_cases: int = 3) -> list[dict[str, Any]]:
    """Analyze review cases into repeatable improvement patterns."""
    patterns = []
    patterns.extend(find_ignore_rule_patterns(cases, min_cases))
    patterns.extend(find_classification_override_patterns(cases, min_cases))
    patterns.extend(find_priority_patterns(cases, min_cases))
    patterns.extend(find_prompt_patterns(cases, min_cases))
    patterns.sort(key=lambda item: (item.get("sample_size", 0), item.get("kind", "")), reverse=True)
    return patterns
