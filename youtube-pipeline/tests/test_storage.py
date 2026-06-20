import tempfile
import unittest
from pathlib import Path

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.storage import cleanup_media, cleanup_video_media, get_storage_status


class TestConfig:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.output_dir = Path("downloads")
        self.db_path = base_dir / "pipeline.db"
        self.storage_max_gb = 1
        self.storage_warn_gb = 0
        self.storage_min_free_gb = 0
        self.storage_retention_days = 0
        self.storage_published_retention_days = 0
        self.storage_cleanup_enabled = False
        self.storage_cleanup_statuses = "published,skipped,failed"

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.base_dir / path


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.config = TestConfig(self.base_dir)
        self.output_dir = self.config.resolve_path(str(self.config.output_dir))
        self.output_dir.mkdir(parents=True)
        self.conn = connect(self.config.db_path)
        init_schema(self.conn)
        self.repo = Repository(self.conn)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.temp_dir.cleanup)

    def _published_video_with_files(self, video_id: str = "abc123def45") -> Path:
        video_dir = self.output_dir / video_id
        video_dir.mkdir()
        merged = video_dir / f"{video_id}_merge.mp4"
        meta = video_dir / "meta.json"
        merged.write_bytes(b"video-data")
        meta.write_text("{}", encoding="utf-8")
        self.repo.upsert_video(video_id, f"https://www.youtube.com/watch?v={video_id}")
        self.repo.update_video_status(video_id, "downloading")
        self.repo.update_video_status(video_id, "downloaded")
        self.repo.update_video_status(video_id, "ready_to_publish")
        self.repo.update_video_status(video_id, "publishing")
        self.repo.update_video_status(video_id, "published")
        self.repo.save_media_files(video_id, meta_path=str(meta), merged_path=str(merged))
        return merged

    def test_storage_status_reports_sizes_and_cleanup_preview(self):
        self._published_video_with_files()

        status = get_storage_status(self.config)

        self.assertGreater(status["total_size_bytes"], 0)
        self.assertEqual(status["cleanup_preview"]["count"], 1)
        self.assertEqual(status["by_status"][0]["status"], "published")

    def test_published_retention_uses_publish_record_time(self):
        self.config.storage_published_retention_days = 7
        self._published_video_with_files()
        self.repo.save_publish_record(
            "abc123def45",
            platform="bilibili",
            account="test",
            status="published",
            published_at="2099-01-01T00:00:00+00:00",
        )

        status = get_storage_status(self.config)

        self.assertEqual(status["cleanup_preview"]["count"], 0)

    def test_old_published_record_becomes_cleanup_candidate(self):
        self.config.storage_published_retention_days = 7
        self._published_video_with_files()
        self.repo.save_publish_record(
            "abc123def45",
            platform="bilibili",
            account="test",
            status="published",
            published_at="2000-01-01T00:00:00+00:00",
        )

        status = get_storage_status(self.config)
        item = status["cleanup_preview"]["items"][0]

        self.assertEqual(status["cleanup_preview"]["count"], 1)
        self.assertEqual(item["cleanup_reason"], "published_at")
        self.assertEqual(item["retention_days"], 7)

    def test_cleanup_media_dry_run_keeps_files(self):
        merged = self._published_video_with_files()

        result = cleanup_media(self.config, dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertTrue(merged.exists())
        self.assertTrue(self.repo.get_media_files("abc123def45")["merged_path"])

    def test_cleanup_media_deletes_files_and_clears_media_paths(self):
        merged = self._published_video_with_files()

        result = cleanup_media(self.config, dry_run=False)
        media = self.repo.get_media_files("abc123def45")

        self.assertEqual(result["status"], "cleaned")
        self.assertFalse(merged.exists())
        self.assertEqual(media["merged_path"], "")
        self.assertEqual(media["meta_path"], "")
        events = self.repo.list_events(video_id="abc123def45", limit=20)
        self.assertTrue(any(event["event_type"] == "storage_media_cleaned" for event in events))

    def test_cleanup_video_media_dry_run_keeps_files(self):
        merged = self._published_video_with_files()

        result = cleanup_video_media(self.config, "abc123def45", dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["item"]["size_bytes"], len(b"video-data") + len(b"{}"))
        self.assertTrue(merged.exists())

    def test_cleanup_video_media_blocks_ineligible_status_without_force(self):
        video_id = "abc123def45"
        video_dir = self.output_dir / video_id
        video_dir.mkdir()
        merged = video_dir / f"{video_id}_merge.mp4"
        merged.write_bytes(b"video-data")
        self.repo.upsert_video(video_id, f"https://www.youtube.com/watch?v={video_id}")
        self.repo.save_media_files(video_id, merged_path=str(merged))

        with self.assertRaises(RuntimeError):
            cleanup_video_media(self.config, video_id, dry_run=False)

        result = cleanup_video_media(self.config, video_id, dry_run=False, force=True)
        self.assertEqual(result["status"], "cleaned")
        self.assertFalse(merged.exists())


if __name__ == "__main__":
    unittest.main()
