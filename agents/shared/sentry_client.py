#!/usr/bin/env python3
"""Sentry API client (reuse from existing script)."""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class SentryClient:
    """Sentry API client."""

    def __init__(self, base_url: str, token: str):
        """
        Initialize Sentry client.

        Args:
            base_url: Sentry base URL
            token: Auth token
        """
        self.base_url = base_url.rstrip('/')
        if not self.base_url.startswith('http'):
            self.base_url = 'https://' + self.base_url

        self.token = token
        self.auth_mode = "bearer"
        self.timeout = 30

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """
        GET request to Sentry API.

        Args:
            path: API path (e.g., "/api/0/organizations/")
            params: Query parameters

        Returns:
            Parsed JSON response

        Raises:
            RuntimeError: If request fails
        """
        return self._request("GET", path, params=params)

    def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> Any:
        """Make HTTP request to Sentry API."""
        url = self.base_url + path
        if params:
            query = urllib.parse.urlencode(params, doseq=True)
            url = f"{url}?{query}"

        request = urllib.request.Request(url, method=method)
        request.add_header("Accept", "application/json")
        self._add_auth(request)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else None

        except urllib.error.HTTPError as exc:
            # Try basic auth if bearer fails
            if exc.code in (401, 403) and self.auth_mode == "bearer":
                self.auth_mode = "basic"
                return self._request(method, path, params)

            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Sentry API {exc.code} for {url}: {detail}") from exc

        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Sentry API at {url}: {exc}") from exc

    def _add_auth(self, request: urllib.request.Request) -> None:
        """Add authentication header."""
        if self.auth_mode == "basic":
            raw = f"{self.token}:".encode("utf-8")
            request.add_header(
                "Authorization", "Basic " + base64.b64encode(raw).decode("ascii")
            )
        else:
            request.add_header("Authorization", f"Bearer {self.token}")


def discover_org(client: SentryClient) -> str:
    """
    Discover organization slug from API.

    Args:
        client: Sentry client

    Returns:
        Organization slug

    Raises:
        RuntimeError: If no organizations found
    """
    orgs = client.get("/api/0/organizations/")
    if not isinstance(orgs, list) or not orgs:
        raise RuntimeError("No Sentry organizations found")

    slug = orgs[0].get("slug") or orgs[0].get("id")
    if not slug:
        raise RuntimeError("Organization has no slug")

    return str(slug)


def get_cache_dir() -> Path:
    """Get cache directory for project ID mappings."""
    # Use XDG_CACHE_HOME or fallback to ~/.cache
    cache_home = os.environ.get('XDG_CACHE_HOME')
    if cache_home:
        cache_dir = Path(cache_home) / 'sentry-alert-agent'
    else:
        cache_dir = Path.home() / '.cache' / 'sentry-alert-agent'

    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def load_project_cache(org: str, base_url: str) -> dict[str, str]:
    """
    Load cached project name -> ID mappings.

    Args:
        org: Organization slug
        base_url: Sentry base URL

    Returns:
        Dict of project_name -> project_id
    """
    cache_dir = get_cache_dir()
    # Create cache filename from org and base_url hash
    cache_key = f"{org}_{hash(base_url)}"
    cache_file = cache_dir / f"projects_{cache_key}.json"

    if not cache_file.exists():
        return {}

    try:
        with cache_file.open('r', encoding='utf-8') as f:
            cache_data = json.load(f)

        # Check cache age (expire after 30 days)
        cached_at = cache_data.get('cached_at')
        if cached_at:
            cached_time = dt.datetime.fromisoformat(cached_at)
            age = dt.datetime.now(dt.timezone.utc) - cached_time
            if age.total_seconds() > 2592000:  # 30 days (30 * 24 * 3600)
                return {}  # Cache expired

        return cache_data.get('projects', {})

    except Exception:
        return {}  # Ignore cache errors


def save_project_cache(org: str, base_url: str, projects: dict[str, str]) -> None:
    """
    Save project name -> ID mappings to cache.

    Args:
        org: Organization slug
        base_url: Sentry base URL
        projects: Dict of project_name -> project_id
    """
    cache_dir = get_cache_dir()
    cache_key = f"{org}_{hash(base_url)}"
    cache_file = cache_dir / f"projects_{cache_key}.json"

    try:
        cache_data = {
            'cached_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'org': org,
            'base_url': base_url,
            'projects': projects
        }

        with cache_file.open('w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=2)

    except Exception:
        pass  # Ignore cache write errors


def resolve_projects(
    client: SentryClient,
    org: str,
    project_specs: list[str],
    use_cache: bool = True
) -> list[str]:
    """
    Resolve project names/slugs to project IDs (with caching).

    Args:
        client: Sentry client
        org: Organization slug
        project_specs: List of project names, slugs, or IDs
        use_cache: Whether to use cached mappings (default: True)

    Returns:
        List of project IDs

    Raises:
        RuntimeError: If projects not found
    """
    if not project_specs or project_specs == ["-1"]:
        return ["-1"]  # All projects

    # If all specs are already numeric IDs, return as-is
    if all(spec == "-1" or spec.isdigit() for spec in project_specs):
        return project_specs

    # Try cache first
    by_slug_or_name: dict[str, str] = {}
    if use_cache:
        by_slug_or_name = load_project_cache(org, client.base_url)

    # If cache miss or incomplete, fetch from API
    missing_specs = [
        spec for spec in project_specs
        if spec.lower() not in by_slug_or_name and not spec.isdigit()
    ]

    if missing_specs or not by_slug_or_name:
        # Fetch all projects from API
        projects = client.get(f"/api/0/organizations/{urllib.parse.quote(org)}/projects/")

        if not isinstance(projects, list):
            raise RuntimeError("Unexpected Sentry projects response")

        # Build lookup map: name/slug -> ID
        for project in projects:
            project_id = str(project.get("id") or "")
            for key in (project.get("slug"), project.get("name"), project_id):
                if key:
                    by_slug_or_name[str(key).lower()] = project_id

        # Save to cache
        if use_cache:
            save_project_cache(org, client.base_url, by_slug_or_name)

    # Resolve each spec
    resolved: list[str] = []
    missing: list[str] = []

    for spec in project_specs:
        if spec == "-1" or spec.isdigit():
            resolved.append(spec)
            continue

        project_id = by_slug_or_name.get(spec.lower())
        if project_id:
            resolved.append(project_id)
        else:
            missing.append(spec)

    if missing:
        known = ", ".join(sorted(set(
            name for name in by_slug_or_name.keys() if not name.isdigit()
        ))[:10])
        raise RuntimeError(
            f"Unknown Sentry project(s): {', '.join(missing)}. "
            f"Known projects: {known} (showing first 10)"
        )

    return resolved


def fetch_issues(
    client: SentryClient,
    org: str,
    stats_period: str,
    query: str = "is:unresolved",
    projects: list[str] | None = None,
    environment: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    Fetch Sentry issues.

    Args:
        client: Sentry client
        org: Organization slug
        stats_period: Time period (e.g., "1h", "7d")
        query: Search query
        projects: Project IDs (numbers) or None for all
        environment: Environment filter
        limit: Max issues to fetch

    Returns:
        List of issue dicts

    Raises:
        RuntimeError: If request fails
    """
    params: dict[str, Any] = {
        "query": query,
        "statsPeriod": stats_period,
        "sort": "freq",
        "limit": min(limit, 100),
        "expand": ["owners"],
    }

    if projects:
        params["project"] = projects

    if environment:
        params["environment"] = [environment]

    issues = client.get(f"/api/0/organizations/{urllib.parse.quote(org)}/issues/", params)

    if not isinstance(issues, list):
        raise RuntimeError("Unexpected Sentry response (expected list)")

    return issues[:limit]
