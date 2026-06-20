import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.worker.runner import run_worker_loop, run_worker_once


class WorkerRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pipeline.db"
        self.config = SimpleNamespace(
            db_path=self.db_path,
            pipeline_enabled=True,
            worker_enable_discovery=True,
            worker_enable_download=True,
            worker_enable_describe=True,
            worker_discovery_min_queue_size=3,
            worker_discovery_source=None,
            worker_enable_publish=False,
            worker_publish_dry_run=True,
            worker_interval_seconds=1,
            worker_cron="",
            job_lease_seconds=1800,
            storage_cleanup_enabled=False,
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
        self.assertEqual([step["step"] for step in result["steps"]], ["recover", "discovery", "download", "describe", "publish", "storage_cleanup"])
        self.assertEqual(result["steps"][4]["result"]["reason"], "worker_publish_disabled")
        self.assertEqual(result["steps"][5]["result"]["reason"], "storage_cleanup_disabled")
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

    def test_run_worker_once_skips_steps_when_pipeline_disabled(self):
        self.config.pipeline_enabled = False
        with (
            patch("app.worker.runner.discover_videos") as discover_videos,
            patch("app.worker.runner.download_next") as download_next,
            patch("app.worker.runner.describe_next") as describe_next,
            patch("app.worker.runner.publish_next") as publish_next,
        ):
            result = run_worker_once(self.config, enable_publish=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual([step["result"]["reason"] for step in result["steps"][1:]], ["pipeline_disabled"] * 5)
        discover_videos.assert_not_called()
        download_next.assert_not_called()
        describe_next.assert_not_called()
        publish_next.assert_not_called()

    def test_run_worker_once_respects_download_and_describe_switches(self):
        self.config.worker_enable_download = False
        self.config.worker_enable_describe = False
        with (
            patch("app.worker.runner.discover_videos", return_value={"inserted_count": 0, "accepted_count": 0}),
            patch("app.worker.runner.download_next") as download_next,
            patch("app.worker.runner.describe_next") as describe_next,
        ):
            result = run_worker_once(self.config)

        self.assertEqual(result["steps"][2]["result"]["reason"], "worker_download_disabled")
        self.assertEqual(result["steps"][3]["result"]["reason"], "worker_describe_disabled")
        download_next.assert_not_called()
        describe_next.assert_not_called()

    def test_run_worker_once_runs_storage_cleanup_when_enabled(self):
        self.config.storage_cleanup_enabled = True
        with (
            patch("app.worker.runner.discover_videos", return_value={"inserted_count": 0, "accepted_count": 0}),
            patch("app.worker.runner.download_next", return_value={"status": "empty"}),
            patch("app.worker.runner.describe_next", return_value={"status": "empty"}),
            patch("app.worker.runner.cleanup_media", return_value={"status": "cleaned", "count": 1}) as cleanup_media,
        ):
            result = run_worker_once(self.config)

        self.assertEqual(result["steps"][-1]["step"], "storage_cleanup")
        self.assertEqual(result["steps"][-1]["result"]["status"], "cleaned")
        cleanup_media.assert_called_once_with(self.config, dry_run=False)

    def test_run_worker_loop_uses_cron_when_configured(self):
        self.config.worker_cron = "*/5 * * * *"
        with (
            patch("app.worker.runner.run_worker_once", return_value={"status": "ok"}),
            patch("app.worker.runner.seconds_until_next_cron", return_value=0.01) as seconds_until_next_cron,
            patch("app.worker.runner.time.sleep") as sleep,
        ):
            result = run_worker_loop(self.config, max_runs=2, config_loader=None)

        self.assertEqual(result["schedule_mode"], "cron")
        seconds_until_next_cron.assert_called_once()
        sleep.assert_called_once_with(0.01)

    def test_run_worker_loop_interval_overrides_cron(self):
        self.config.worker_cron = "*/5 * * * *"
        with (
            patch("app.worker.runner.run_worker_once", return_value={"status": "ok"}),
            patch("app.worker.runner.seconds_until_next_cron") as seconds_until_next_cron,
            patch("app.worker.runner.time.sleep") as sleep,
        ):
            result = run_worker_loop(self.config, interval_seconds=7, max_runs=2, config_loader=None)

        self.assertEqual(result["schedule_mode"], "interval")
        seconds_until_next_cron.assert_not_called()
        sleep.assert_called_once_with(7)

    def test_run_worker_loop_reloads_config_each_run_and_before_sleep(self):
        first = SimpleNamespace(**self.config.__dict__)
        first.worker_cron = ""
        first.worker_interval_seconds = 3
        second = SimpleNamespace(**self.config.__dict__)
        second.worker_cron = "*/5 * * * *"
        second.worker_interval_seconds = 9
        loader_values = [first, second, second]
        seen_intervals = []

        def load_next():
            return loader_values.pop(0)

        def fake_run_worker_once(config, **kwargs):
            seen_intervals.append(config.worker_interval_seconds)
            return {"status": "ok"}

        with (
            patch("app.worker.runner.run_worker_once", side_effect=fake_run_worker_once),
            patch("app.worker.runner.seconds_until_next_cron", return_value=0.01) as seconds_until_next_cron,
            patch("app.worker.runner.time.sleep") as sleep,
        ):
            result = run_worker_loop(self.config, max_runs=2, config_loader=load_next)

        self.assertEqual(seen_intervals, [3, 9])
        self.assertEqual(result["schedule_mode"], "cron")
        seconds_until_next_cron.assert_called_once()
        sleep.assert_called_once_with(0.01)


if __name__ == "__main__":
    unittest.main()
