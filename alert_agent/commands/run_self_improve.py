"""Generate read-only self-improvement proposals from manual review outcomes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Sequence

from alert_agent.core.ai_client import PiAIClient
from alert_agent.core.config_loader import load_agent_config
from alert_agent.improvement.analyzer import analyze_review_cases
from alert_agent.improvement.collector import build_review_cases, read_audit_events
from alert_agent.improvement.proposer import build_proposals, write_proposal_bundle


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/agent_config.yaml", help="Config file path")
    parser.add_argument("--force", action="store_true", help="Run even if there are no new manual review events")
    parser.add_argument("--dry-run", action="store_true", help="Print proposals without writing files")
    return parser.parse_args(argv)


def state_path(config: dict[str, Any]) -> Path:
    explicit = str(config.get("state_file") or "").strip()
    if explicit:
        return Path(explicit)
    metrics_dir = Path(config.get("metrics_dir", "./output/metrics"))
    return metrics_dir / "self_improve_state.json"


def load_state(config: dict[str, Any]) -> dict[str, Any]:
    path = state_path(config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(config: dict[str, Any], payload: dict[str, Any]) -> None:
    path = state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def has_new_review_events(config_file: str, config: dict[str, Any], previous_state: dict[str, Any]) -> tuple[bool, int]:
    from alert_agent.core.manual_review import load_paths

    review_paths = load_paths(config_file)
    events = read_audit_events(review_paths)
    count = len(events)
    return count > int(previous_state.get("last_audit_event_count") or 0), count


def build_ai_client(config: dict[str, Any]) -> PiAIClient | None:
    ai_config = dict(config.get("ai") or {})
    if str(ai_config.get("enabled", "true")).lower() not in {"1", "true", "yes", "on"}:
        return None

    extra_env = {
        "AZURE_OPENAI_API_KEY": str(ai_config.get("api_key") or ""),
        "AZURE_OPENAI_BASE_URL": str(ai_config.get("base_url") or ""),
        "AZURE_OPENAI_DEPLOYMENT_NAME_MAP": str(ai_config.get("deployment_name_map") or ""),
        "AI_TIMEOUT": str(ai_config.get("timeout") or ""),
    }
    return PiAIClient(
        provider=str(ai_config.get("provider") or "azure-openai-responses"),
        model=str(ai_config.get("model") or "") or None,
        api_key=str(ai_config.get("api_key") or "") or None,
        metrics_dir=config.get("metrics_dir"),
        agent_name="self_improve",
        run_id=config.get("run_id"),
        pricing=config.get("ai_pricing"),
        extra_env=extra_env,
    )


def run(config_file: str, config: dict[str, Any], *, force: bool = False, dry_run: bool = False) -> int:
    if str(config.get("enabled", "false")).lower() not in {"1", "true", "yes", "on"}:
        print("Self-improve is disabled")
        return 0

    state = load_state(config)
    changed, event_count = has_new_review_events(config_file, config, state)
    if not force and not changed:
        print("No new manual review events since last self-improve run")
        return 0

    cases = build_review_cases(config_file)
    min_cases = int(config.get("min_review_events", 3) or 3)
    patterns = analyze_review_cases(cases, min_cases=min_cases)
    ai_client = build_ai_client(config)
    max_proposals = int(config.get("max_proposals", 12) or 12)
    proposals = build_proposals(patterns[:max_proposals], ai_client=ai_client)

    output_dir = Path(config.get("output_dir", "./output/improvement")) / "proposals"
    if dry_run:
        print(json.dumps({"proposal_count": len(proposals), "proposals": proposals}, indent=2))
    else:
        bundle_path = write_proposal_bundle(output_dir, proposals)
        print(f"Wrote {len(proposals)} proposals to {bundle_path}")

    if not dry_run:
        save_state(
            config,
            {
                "last_run_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "last_audit_event_count": event_count,
                "last_proposal_count": len(proposals),
            },
        )
    return 2 if proposals else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_agent_config("self_improve", args.config)
    return run(args.config, config, force=args.force, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
