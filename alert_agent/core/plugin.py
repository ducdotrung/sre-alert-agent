"""Plugin contracts for multi-source alert handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .models import AlertRecord


@dataclass
class PolicyPack:
    """Source or team-specific rules and prompts."""

    name: str
    classification_rules: Path
    priority_thresholds: Path
    ignore_rules: Path
    prompts: dict[str, Path] = field(default_factory=dict)


@dataclass
class PipelineContext:
    """Shared runtime context for pipeline stages."""

    config_file: str
    repo_root: Path
    output_dir: Path
    metrics_dir: Path
    run_id: str | None
    stage_config: dict[str, Any]
    source_config: dict[str, Any]


class SourcePlugin(Protocol):
    """Minimal plugin contract for one alert source."""

    name: str

    def fetch_alerts(self, context: PipelineContext, **kwargs: Any) -> list[dict[str, Any]]:
        ...

    def normalize_alert(self, raw_alert: dict[str, Any], context: PipelineContext) -> AlertRecord:
        ...

    def load_policy_pack(self, context: PipelineContext) -> PolicyPack:
        ...
