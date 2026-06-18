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


if __name__ == "__main__":
    unittest.main()
