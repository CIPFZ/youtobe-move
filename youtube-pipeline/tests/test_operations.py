import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.operations import pipeline_status, retry_video, skip_video


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pipeline.db"
        self.config = SimpleNamespace(db_path=self.db_path)
        self.conn = connect(self.db_path)
        init_schema(self.conn)
        self.repo = Repository(self.conn)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.temp_dir.cleanup)

    def test_pipeline_status_counts_videos_jobs_and_events(self):
        self.repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        self.repo.create_job("download", video_id="abc123def45")

        status = pipeline_status(self.config)

        self.assertEqual(status["videos_by_status"][0]["status"], "selected")
        self.assertEqual(status["videos_by_status"][0]["count"], 1)
        self.assertEqual(status["active_queue_count"], 1)
        self.assertEqual(status["jobs_by_type_status"][0]["job_type"], "download")
        self.assertTrue(status["recent_events"])

    def test_retry_failed_download_returns_to_selected_and_creates_job(self):
        self.repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        job_id = self.repo.create_job("download", video_id="abc123def45")
        self.repo.update_video_status("abc123def45", "downloading")
        self.repo.update_video_status("abc123def45", "failed", error="network failed")
        self.repo.update_job_status(job_id, "failed", error="network failed")

        result = retry_video("abc123def45", self.config)

        self.assertEqual(result["job_type"], "download")
        self.assertEqual(result["video"]["status"], "selected")
        new_job = self.repo.get_latest_job("abc123def45", "download")
        self.assertEqual(new_job["status"], "pending")

    def test_retry_failed_publish_returns_to_ready_to_publish(self):
        self.repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        self.repo.update_video_status("abc123def45", "downloading")
        self.repo.update_video_status("abc123def45", "downloaded")
        self.repo.update_video_status("abc123def45", "ready_to_publish")
        job_id = self.repo.create_job("publish", video_id="abc123def45")
        self.repo.update_video_status("abc123def45", "publishing")
        self.repo.update_video_status("abc123def45", "failed", error="publish failed")
        self.repo.update_job_status(job_id, "failed", error="publish failed")

        result = retry_video("abc123def45", self.config)

        self.assertEqual(result["job_type"], "publish")
        self.assertEqual(result["video"]["status"], "ready_to_publish")

    def test_skip_selected_video(self):
        self.repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")

        result = skip_video("abc123def45", self.config)

        self.assertEqual(result["video"]["status"], "skipped")

    def test_skip_active_video_requires_force(self):
        self.repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        self.repo.update_video_status("abc123def45", "downloading")

        with self.assertRaises(RuntimeError):
            skip_video("abc123def45", self.config)

        result = skip_video("abc123def45", self.config, force=True)
        self.assertEqual(result["video"]["status"], "skipped")

    def test_skip_published_video_is_blocked(self):
        self.repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        self.repo.update_video_status("abc123def45", "downloading")
        self.repo.update_video_status("abc123def45", "downloaded")
        self.repo.update_video_status("abc123def45", "ready_to_publish")
        self.repo.update_video_status("abc123def45", "publishing")
        self.repo.update_video_status("abc123def45", "published")

        with self.assertRaises(RuntimeError):
            skip_video("abc123def45", self.config, force=True)


if __name__ == "__main__":
    unittest.main()
