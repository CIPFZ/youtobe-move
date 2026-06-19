import tempfile
import unittest
from pathlib import Path

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema


class CoreRepositoryTests(unittest.TestCase):
    def _repo(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "pipeline.db"
        conn = connect(db_path)
        init_schema(conn)
        self.addCleanup(conn.close)
        self.addCleanup(temp_dir.cleanup)
        return Repository(conn)

    def test_upsert_video_creates_video_and_event(self):
        repo = self._repo()

        video = repo.upsert_video(
            video_id="abc123def45",
            source_url="https://www.youtube.com/watch?v=abc123def45",
        )

        self.assertEqual(video["video_id"], "abc123def45")
        self.assertEqual(video["status"], "selected")
        events = repo.list_events("abc123def45")
        self.assertEqual(events[0]["event_type"], "video_created")

    def test_update_video_status_validates_transition_and_writes_event(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")

        video = repo.update_video_status("abc123def45", "downloading")

        self.assertEqual(video["status"], "downloading")
        events = repo.list_events("abc123def45")
        self.assertEqual(events[0]["event_type"], "status_changed")

    def test_update_video_status_rejects_invalid_transition(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")

        with self.assertRaises(ValueError):
            repo.update_video_status("abc123def45", "published")

    def test_save_metadata_and_media_files(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")

        repo.save_metadata("abc123def45", ytdlp_meta={"id": "abc123def45"})
        repo.save_media_files("abc123def45", merged_path="runtime/downloads/abc123def45/abc123def45_merge.mp4")

        metadata = repo.conn.execute("SELECT * FROM video_metadata WHERE video_id=?", ("abc123def45",)).fetchone()
        files = repo.conn.execute("SELECT * FROM media_files WHERE video_id=?", ("abc123def45",)).fetchone()
        self.assertIn("abc123def45", metadata["ytdlp_meta_json"])
        self.assertTrue(files["merged_path"].endswith("abc123def45_merge.mp4"))

    def test_job_helpers_find_and_update_pending_job(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        job_id = repo.create_job("download", video_id="abc123def45", payload={"url": "https://example.test"})

        pending = repo.get_pending_job("download", video_id="abc123def45")
        self.assertEqual(pending["id"], job_id)

        running = repo.update_job_status(job_id, "running")
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["attempts"], 1)
        self.assertIsNone(repo.get_pending_job("download", video_id="abc123def45"))

    def test_pending_job_respects_next_run_at(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        future_job_id = repo.create_job(
            "download",
            video_id="abc123def45",
            next_run_at="2999-01-01 00:00:00",
        )

        self.assertIsNone(repo.get_pending_job("download"))
        self.assertIsNone(repo.get_pending_job("download", video_id="abc123def45"))
        self.assertEqual(repo.get_pending_job("download", video_id="abc123def45", include_future=True)["id"], future_job_id)

        repo.update_job_status(future_job_id, "pending", next_run_at="2000-01-01 00:00:00")
        pending = repo.get_pending_job("download")
        self.assertEqual(pending["id"], future_job_id)


if __name__ == "__main__":
    unittest.main()
