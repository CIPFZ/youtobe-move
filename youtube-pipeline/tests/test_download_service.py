import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.download_service import download_next, download_video_from_db


class DownloadServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.db_path = self.base_dir / "pipeline.db"
        self.config = SimpleNamespace(db_path=self.db_path)

        self.conn = connect(self.db_path)
        init_schema(self.conn)
        self.repo = Repository(self.conn)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.temp_dir.cleanup)

    def _add_video(self, video_id="abc123def45"):
        self.repo.upsert_video(video_id, f"https://www.youtube.com/watch?v={video_id}")
        return video_id

    def test_download_video_from_db_updates_status_job_and_media_files(self):
        video_id = self._add_video()
        meta_path = self.base_dir / "downloads" / video_id / "meta.json"
        merged_path = self.base_dir / "downloads" / video_id / f"{video_id}_merge.mp4"

        def fake_download(url, config, event_callback=None):
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text("{}", encoding="utf-8")
            merged_path.write_bytes(b"merged")
            if event_callback:
                event_callback("metadata_saved", "Metadata saved", {"path": str(meta_path)})
                event_callback("merge_done", "Video and audio merged", {"path": str(merged_path)})
            return {
                "video_id": video_id,
                "title": "Test title",
                "channel": "Test channel",
                "duration": 12,
                "view_count": 34,
                "category": "Film & Animation",
                "output_dir": str(meta_path.parent),
                "meta": str(meta_path),
                "video": str(meta_path.parent / "video.mp4"),
                "audio": str(meta_path.parent / "audio.m4a"),
                "poster": str(meta_path.parent / "poster.jpg"),
                "merged": str(merged_path),
            }

        with patch("app.download_service.download_video_assets", side_effect=fake_download):
            result = download_video_from_db(video_id, self.config)

        video = self.repo.get_video(video_id)
        files = self.repo.get_media_files(video_id)
        job = self.repo.get_latest_job(video_id, "download")
        self.assertEqual(result["status"], "downloaded")
        self.assertEqual(video["status"], "downloaded")
        self.assertEqual(video["title"], "Test title")
        self.assertEqual(files["merged_path"], str(merged_path))
        self.assertEqual(job["status"], "succeeded")

    def test_download_video_from_db_skips_existing_download(self):
        video_id = self._add_video()
        merged_path = self.base_dir / "downloads" / video_id / f"{video_id}_merge.mp4"
        merged_path.parent.mkdir(parents=True, exist_ok=True)
        merged_path.write_bytes(b"merged")
        self.repo.save_media_files(video_id, merged_path=str(merged_path))
        self.repo.update_video_status(video_id, "downloading")
        self.repo.update_video_status(video_id, "downloaded")

        result = download_video_from_db(video_id, self.config)

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["merged"], str(merged_path))

    def test_download_video_from_db_marks_failure(self):
        video_id = self._add_video()

        with (
            patch("app.download_service.download_video_assets", side_effect=RuntimeError("network failed")),
            patch("app.download_service.logger.exception"),
        ):
            with self.assertRaises(RuntimeError):
                download_video_from_db(video_id, self.config)

        video = self.repo.get_video(video_id)
        job = self.repo.get_latest_job(video_id, "download")
        self.assertEqual(video["status"], "failed")
        self.assertIn("network failed", video["last_error"])
        self.assertEqual(job["status"], "failed")

    def test_download_next_uses_pending_job(self):
        first_id = self._add_video("first123456")
        second_id = self._add_video("second12345")
        self.repo.create_job("download", video_id=second_id)

        def fake_download(url, config, event_callback=None):
            out_dir = self.base_dir / "downloads" / second_id
            out_dir.mkdir(parents=True, exist_ok=True)
            merged = out_dir / f"{second_id}_merge.mp4"
            merged.write_bytes(b"merged")
            return {
                "video_id": second_id,
                "title": "",
                "channel": "",
                "duration": None,
                "view_count": None,
                "category": "",
                "output_dir": str(out_dir),
                "meta": str(out_dir / "meta.json"),
                "video": str(out_dir / "video.mp4"),
                "audio": str(out_dir / "audio.m4a"),
                "poster": "",
                "merged": str(merged),
            }

        with patch("app.download_service.download_video_assets", side_effect=fake_download):
            result = download_next(self.config)

        self.assertEqual(result["video_id"], second_id)
        self.assertEqual(self.repo.get_video(first_id)["status"], "selected")
        self.assertEqual(self.repo.get_video(second_id)["status"], "downloaded")


if __name__ == "__main__":
    unittest.main()
