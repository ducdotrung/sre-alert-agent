"""Helpers for linking issues into the local review UI."""

from __future__ import annotations

from urllib.parse import quote, urlencode


def normalize_review_web_base_url(base_url: str | None) -> str:
    """Normalize the configured review UI base URL."""
    return str(base_url or "").strip().rstrip("/")


def build_review_issue_url(base_url: str | None, issue_id: str, status: str | None = None) -> str:
    """Build a direct link to an issue in the review UI."""
    normalized = normalize_review_web_base_url(base_url)
    if not normalized or not issue_id:
        return ""

    query = f"?{urlencode({'status': status})}" if status else ""
    return f"{normalized}/issue/{quote(issue_id)}{query}"


def build_review_queue_url(base_url: str | None, status: str | None = None) -> str:
    """Build a link to the review queue page."""
    normalized = normalize_review_web_base_url(base_url)
    if not normalized:
        return ""
    if not status:
        return normalized
    return f"{normalized}/?{urlencode({'status': status})}"
