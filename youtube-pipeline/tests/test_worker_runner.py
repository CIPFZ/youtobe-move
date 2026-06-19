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
            worker_enable_discovery=True,
            worker_discovery_min_queue_size=3,
            worker_discovery_source=None,
            worker_enable_publish=False,
            worker_publish_dry_run=True,
            worker_interval_seconds=1,
            job_lease_seconds=1800,
        )
        self.addCleanup(self.temp_dir.cleanup)

    def _events(self):
        with connect(self.db_path) as conn:
            init_schema(conn)
            repo = Repository(conn)
            return repo.list_events(limit=20)

    def test_run_worker_once_runs_download_and_describe_with_publish_disabled(self):
        with (
            patch("app.worker.runner.discover_videos", return_value={"inserted_count": 0, "accepted_count": 0}),
            patch("app.worker.runner.download_next", return_value={"status": "empty"}),
            patch("app.worker.runner.describe_next", return_value={"status": "ready_to_publish"}),
            patch("app.worker.runner.publish_next") as publish_next,
        ):
            result = run_worker_once(self.config)

        self.assertEqual(result["status"], "ok")
        self.assertEqual([step["step"] for step in result["steps"]], ["recover", "discovery", "download", "describe", "publish"])
        self.assertEqual(result["steps"][4]["result"]["reason"], "worker_publish_disabled")
        publish_next.assert_not_called()
        event_types = [event["event_type"] for event in self._events()]
        self.assertIn("worker_run_started", event_types)
        self.assertIn("worker_run_finished", event_types)

    def test_run_worker_once_can_execute_publish_when_enabled(self):
        with (
            patch("app.worker.runner.discover_videos", return_value={"inserted_count": 0, "accepted_count": 0}),
            patch("app.worker.runner.download_next", return_value={"status": "empty"}),
            patch("app.worker.runner.describe_next", return_value={"status": "empty"}),
            patch("app.worker.runner.publish_next", return_value={"status": "dry_run"}) as publish_next,
        ):
            result = run_worker_once(self.config, enable_publish=True, publish_dry_run=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["steps"][4]["result"]["status"], "dry_run")
        publish_next.assert_called_once()

    def test_run_worker_once_records_step_failure_and_continues(self):
        with (
            patch("app.worker.runner.discover_videos", return_value={"inserted_count": 0, "accepted_count": 0}),
            patch("app.worker.runner.download_next", side_effect=RuntimeError("download failed")),
            patch("app.worker.runner.describe_next", return_value={"status": "empty"}),
            patch("app.worker.runner.publish_next") as publish_next,
            patch("app.worker.runner.logger.exception"),
        ):
            result = run_worker_once(self.config)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["steps"][2]["ok"])
        self.assertEqual(result["steps"][3]["result"]["status"], "empty")
        publish_next.assert_not_called()

    def test_run_worker_once_skips_discovery_when_queue_is_large_enough(self):
        with connect(self.db_path) as conn:
            init_schema(conn)
            repo = Repository(conn)
            for index in range(3):
                repo.upsert_video(
                    f"abc123def4{index}",
                    f"https://www.youtube.com/watch?v=abc123def4{index}",
                    status="selected",
                )
            conn.commit()

        with (
            patch("app.worker.runner.discover_videos") as discover_videos,
            patch("app.worker.runner.download_next", return_value={"status": "empty"}),
            patch("app.worker.runner.describe_next", return_value={"status": "empty"}),
        ):
            result = run_worker_once(self.config)

        self.assertEqual(result["steps"][1]["result"]["status"], "skipped")
        self.assertEqual(result["steps"][1]["result"]["reason"], "queue_above_threshold")
        discover_videos.assert_not_called()


if __name__ == "__main__":
    unittest.main()
