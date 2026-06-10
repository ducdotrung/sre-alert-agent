from __future__ import annotations

import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path

from alert_agent.commands.check_ai_budget import run as run_budget_monitor
from alert_agent.commands.check_pipeline_health import run as run_health_monitor
from alert_agent.commands.check_queue_health import run as run_queue_monitor
from alert_agent.commands.send_daily_summary import run as run_daily_summary


class MonitorCommandTests(unittest.TestCase):
    def test_budget_monitor_dry_run_emits_alert(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_dir = Path(tmpdir) / "metrics"
            metrics_dir.mkdir(parents=True)
            today = dt.datetime.now(dt.timezone.utc)
            ledger = metrics_dir / f"ai_usage-{today.strftime('%Y-%m')}.jsonl"
            ledger.write_text(
                json.dumps(
                    {
                        "timestamp": today.isoformat(),
                        "success": True,
                        "cost_usd": 2.5,
                        "agent": "triage_agent",
                        "operation": "reclassify",
                        "cost_source": "provider",
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            exit_code = run_budget_monitor(
                {
                    "enabled": True,
                    "metrics_dir": str(metrics_dir),
                    "monthly_budget_usd": 1,
                    "daily_budget_usd": 1,
                    "thresholds_percent": "50,80,100",
                },
                dry_run=True,
                stdout=stdout,
            )

            self.assertEqual(exit_code, 2)
            self.assertIn("AI Budget Alert", stdout.getvalue())

    def test_pipeline_health_dry_run_reports_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            metrics_dir = Path(tmpdir) / "metrics"
            metrics_dir.mkdir(parents=True)
            (metrics_dir / "pipeline_state.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "run_id": "run-123",
                        "failure_stage": "review",
                        "exit_code": 1,
                        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            exit_code = run_health_monitor(
                {
                    "enabled": True,
                    "metrics_dir": str(metrics_dir),
                    "stale_run_after_minutes": 120,
                    "stuck_lock_after_minutes": 90,
                },
                dry_run=True,
                stdout=stdout,
            )

            self.assertEqual(exit_code, 2)
            self.assertIn("Pipeline Health Alert [CRITICAL] Failed Run", stdout.getvalue())

    def test_queue_health_dry_run_reports_pending_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            pending_dir = output_dir / "alerts" / "pending"
            pending_dir.mkdir(parents=True)
            (pending_dir / "BACKEND-1.json").write_text("{}", encoding="utf-8")

            stdout = io.StringIO()
            exit_code = run_queue_monitor(
                {
                    "enabled": True,
                    "output_dir": str(output_dir),
                    "metrics_dir": str(output_dir / "metrics"),
                    "pending_threshold": 1,
                    "approved_stale_hours": 4,
                    "recommendation_stale_hours": 2,
                },
                dry_run=True,
                stdout=stdout,
            )

            self.assertEqual(exit_code, 2)
            self.assertIn("Queue Alert [HIGH] Pending Backlog", stdout.getvalue())

    def test_daily_summary_dry_run_forced_prints_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            metrics_dir = root / "metrics"
            output_dir = root / "output"
            (output_dir / "alerts" / "pending").mkdir(parents=True)
            metrics_dir.mkdir(parents=True)

            now = dt.datetime.now(dt.timezone.utc)
            (metrics_dir / f"ai_usage-{now.strftime('%Y-%m')}.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": now.isoformat(),
                        "success": True,
                        "cost_usd": 0.5,
                        "agent": "review_agent",
                        "operation": "review",
                        "cost_source": "provider",
                        "prompt_tokens": 5,
                        "completion_tokens": 3,
                        "total_tokens": 8,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (metrics_dir / "pipeline_state.json").write_text(
                json.dumps({"status": "completed", "updated_at": now.isoformat()}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            exit_code = run_daily_summary(
                {
                    "enabled": True,
                    "metrics_dir": str(metrics_dir),
                    "output_dir": str(output_dir),
                    "send_after_hour_utc": 23,
                },
                dry_run=True,
                force=True,
                stdout=stdout,
            )

            self.assertEqual(exit_code, 2)
            self.assertIn("Daily Monitoring Summary", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
