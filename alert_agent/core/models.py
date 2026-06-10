"""Core alert and pipeline data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AlertRecord:
    """Canonical alert record used by the shared pipeline."""

    alert_id: str
    source: str
    source_type: str
    source_alert_id: str
    title: str
    summary: str = ""
    project: str = ""
    service: str = ""
    platform: str = ""
    environment: str = ""
    severity: str = ""
    status: str = "active"
    count: int = 0
    affected_users: int = 0
    first_seen: str = ""
    last_seen: str = ""
    culprit: str = ""
    link: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    raw_ref: dict[str, str] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

