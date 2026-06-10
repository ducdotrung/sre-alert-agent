from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from alert_agent.core.config_loader import (
    load_pipeline_stage_config,
    load_policy_pack,
    load_source_config,
    substitute_env_vars,
)


class SubstituteEnvVarsTests(unittest.TestCase):
    def test_substitutes_simple_variable(self) -> None:
        with patch.dict(os.environ, {"TEST_SIMPLE": "value"}, clear=False):
            self.assertEqual(substitute_env_vars("${TEST_SIMPLE}"), "value")

    def test_resolves_nested_default_to_fallback_variable(self) -> None:
        with patch.dict(os.environ, {"TEAMS_WEBHOOK_URL": "fallback-url"}, clear=True):
            value = substitute_env_vars("${TEAMS_MONITOR_WEBHOOK_URL:${TEAMS_WEBHOOK_URL:}}")
            self.assertEqual(value, "fallback-url")

    def test_prefers_primary_variable_over_nested_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                "TEAMS_MONITOR_WEBHOOK_URL": "monitor-url",
                "TEAMS_WEBHOOK_URL": "fallback-url",
            },
            clear=True,
        ):
            value = substitute_env_vars("${TEAMS_MONITOR_WEBHOOK_URL:${TEAMS_WEBHOOK_URL:}}")
            self.assertEqual(value, "monitor-url")

    def test_loads_source_and_pipeline_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "agent_config.yaml")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write(
                    """
common:
  output_dir: ./output
sources:
  sentry:
    enabled: true
    kind: sentry
    policy_pack: sentry-default
    config:
      base_url: https://example.invalid
      auth_token: token
pipeline:
  triage:
    lookback_hours: 2
    rule_confidence_threshold: 0.7
policy_packs:
  sentry-default:
    name: sentry-default
    classification_rules: config/classification_rules.yaml
    priority_thresholds: config/priority_thresholds.yaml
    ignore_rules: config/ignore_rules.json
    prompts:
      triage: prompts/triage_reclassify.md
"""
                )

            source = load_source_config("sentry", config_path)
            stage = load_pipeline_stage_config("triage", config_path)
            pack = load_policy_pack("sentry-default", config_path)

            self.assertEqual(source["kind"], "sentry")
            self.assertEqual(source["policy_pack"], "sentry-default")
            self.assertEqual(stage["lookback_hours"], 2)
            self.assertEqual(pack["classification_rules"], "config/classification_rules.yaml")


if __name__ == "__main__":
    unittest.main()
