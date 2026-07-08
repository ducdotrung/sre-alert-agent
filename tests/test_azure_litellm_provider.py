from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from alert_agent.ai_providers.azure_litellm_provider import AzureLiteLLMProvider


class AzureLiteLLMProviderTests(unittest.TestCase):
    def test_timeout_accepts_numeric_string(self) -> None:
        provider = AzureLiteLLMProvider(
            endpoint="https://example.test/openai/v1",
            deployment="test-deployment",
            api_key="test-key",
            timeout="120",
        )
        self.assertEqual(provider.timeout, 120)

    def test_timeout_rejects_invalid_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid Azure LiteLLM timeout"):
            AzureLiteLLMProvider(
                endpoint="https://example.test/openai/v1",
                deployment="test-deployment",
                api_key="test-key",
                timeout="bad-timeout",
            )

    def test_env_deployment_beats_model_alias(self) -> None:
        with patch.dict(os.environ, {"AZURE_LITELLM_DEPLOYMENT": "env-deployment"}, clear=False):
            provider = AzureLiteLLMProvider(
                endpoint="https://example.test/openai/v1",
                model="gpt-5-mini",
                api_key="test-key",
            )
        self.assertEqual(provider.deployment, "env-deployment")


if __name__ == "__main__":
    unittest.main()
