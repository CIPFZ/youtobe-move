import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.worker.runner import run_worker_once


class WorkerRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pipeline.db"
        self.config = SimpleNamespace(
            db_path=self.db_path,
            worker_enable_publish=False,
            worker_publish_dry_run=True,
            worker_interval_seconds=1,
        )
        self.addCleanup(self.temp_dir.cleanup)

    def _events(self):
        with connect(self.db_path) as conn:
            init_schema(conn)
            repo = Repository(conn)
            return repo.list_events(limit=20)

    def test_run_worker_once_runs_download_and_describe_with_publish_disabled(self):
        with (
            patch("app.worker.runner.download_next", return_value={"status": "empty"}),
            patch("app.worker.runner.describe_next", return_value={"status": "ready_to_publish"}),
            patch("app.worker.runner.publish_next") as publish_next,
        ):
            result = run_worker_once(self.config)

        self.assertEqual(result["status"], "ok")
        self.assertEqual([step["step"] for step in result["steps"]], ["download", "describe", "publish"])
        self.assertEqual(result["steps"][2]["result"]["reason"], "worker_publish_disabled")
        publish_next.assert_not_called()
        event_types = [event["event_type"] for event in self._events()]
        self.assertIn("worker_run_started", event_types)
        self.assertIn("worker_run_finished", event_types)

    def test_run_worker_once_can_execute_publish_when_enabled(self):
        with (
            patch("app.worker.runner.download_next", return_value={"status": "empty"}),
            patch("app.worker.runner.describe_next", return_value={"status": "empty"}),
            patch("app.worker.runner.publish_next", return_value={"status": "dry_run"}) as publish_next,
        ):
            result = run_worker_once(self.config, enable_publish=True, publish_dry_run=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["steps"][2]["result"]["status"], "dry_run")
        publish_next.assert_called_once()

    def test_run_worker_once_records_step_failure_and_continues(self):
        with (
            patch("app.worker.runner.download_next", side_effect=RuntimeError("download failed")),
            patch("app.worker.runner.describe_next", return_value={"status": "empty"}),
            patch("app.worker.runner.publish_next") as publish_next,
            patch("app.worker.runner.logger.exception"),
        ):
            result = run_worker_once(self.config)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["steps"][0]["ok"])
        self.assertEqual(result["steps"][1]["result"]["status"], "empty")
        publish_next.assert_not_called()


if __name__ == "__main__":
    unittest.main()
