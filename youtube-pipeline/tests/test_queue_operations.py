import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.operations import add_video_url, add_video_urls


class QueueOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pipeline.db"
        self.config = SimpleNamespace(db_path=self.db_path)
        self.addCleanup(self.temp_dir.cleanup)

    def _repo(self):
        conn = connect(self.db_path)
        init_schema(conn)
        self.addCleanup(conn.close)
        return Repository(conn)

    def test_add_video_url_creates_selected_video_and_download_job(self):
        result = add_video_url(
            "https://www.youtube.com/watch?v=abc123def45",
            self.config,
            priority=10,
            source_label="manual-test",
        )
        repo = self._repo()

        video = repo.get_video("abc123def45")
        job = repo.get_latest_job("abc123def45", "download")
        self.assertEqual(result["status"], "created")
        self.assertEqual(video["status"], "selected")
        self.assertEqual(video["source_url"], "https://www.youtube.com/watch?v=abc123def45")
        self.assertEqual(video["priority"], 10)
        self.assertEqual(video["source_label"], "manual-test")
        self.assertEqual(job["status"], "pending")

    def test_add_video_url_does_not_duplicate_existing_video_or_job(self):
        first = add_video_url("https://www.youtube.com/watch?v=abc123def45", self.config)
        second = add_video_url("https://youtu.be/abc123def45", self.config)
        repo = self._repo()

        jobs = repo.conn.execute("SELECT * FROM jobs WHERE video_id=?", ("abc123def45",)).fetchall()
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "exists")
        self.assertEqual(len(jobs), 1)

    def test_add_video_urls_reports_partial_errors(self):
        result = add_video_urls(
            [
                "https://www.youtube.com/watch?v=abc123def45",
                "not-a-youtube-url",
                "https://youtu.be/abc123def45",
            ],
            self.config,
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["created_count"], 1)
        self.assertEqual(result["exists_count"], 1)
        self.assertEqual(result["error_count"], 1)

    def test_list_videos_orders_by_priority(self):
        add_video_url("https://www.youtube.com/watch?v=low12345678", self.config, priority=200)
        add_video_url("https://www.youtube.com/watch?v=high1234567", self.config, priority=10)
        repo = self._repo()

        rows = repo.list_videos(status="selected")

        self.assertEqual([row["video_id"] for row in rows], ["high1234567", "low12345678"])


if __name__ == "__main__":
    unittest.main()
