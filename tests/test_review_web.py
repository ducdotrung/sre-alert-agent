from __future__ import annotations

import unittest

from scripts.review_web import app_path, normalize_path_prefix, resolve_request_path, strip_path_prefix


class ReviewWebPathTests(unittest.TestCase):
    def test_normalize_path_prefix_from_base_url(self) -> None:
        self.assertEqual(
            normalize_path_prefix("https://alerts.example.com/sre-alert-review/"),
            "/sre-alert-review",
        )

    def test_normalize_path_prefix_for_root_url(self) -> None:
        self.assertEqual(normalize_path_prefix("https://alerts.example.com/"), "")

    def test_app_path_with_prefix(self) -> None:
        self.assertEqual(app_path("/sre-alert-review", "/metrics"), "/sre-alert-review/metrics")
        self.assertEqual(app_path("/sre-alert-review", "/"), "/sre-alert-review/")

    def test_strip_path_prefix(self) -> None:
        self.assertEqual(strip_path_prefix("/sre-alert-review/metrics", "/sre-alert-review"), "/metrics")
        self.assertEqual(strip_path_prefix("/sre-alert-review", "/sre-alert-review"), "/")
        self.assertIsNone(strip_path_prefix("/metrics", "/sre-alert-review"))

    def test_resolve_request_path_prefers_configured_prefix(self) -> None:
        self.assertEqual(
            resolve_request_path("/sre-alert-review/metrics", "/sre-alert-review"),
            ("/sre-alert-review", "/metrics"),
        )

    def test_resolve_request_path_allows_root_fallback(self) -> None:
        self.assertEqual(
            resolve_request_path("/metrics", "/sre-alert-review"),
            ("", "/metrics"),
        )


if __name__ == "__main__":
    unittest.main()
