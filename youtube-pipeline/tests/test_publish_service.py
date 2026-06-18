import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.publish_service import describe_video, publish_video


class PublishServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.db_path = self.base_dir / "pipeline.db"
        self.config = SimpleNamespace(
            db_path=self.db_path,
            bilibili_account="mybili",
            bilibili_tid_options="27:动画-综合,188:科技",
        )
        self.conn = connect(self.db_path)
        init_schema(self.conn)
        self.repo = Repository(self.conn)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.temp_dir.cleanup)

    def _add_downloaded_video(self, video_id="abc123def45"):
        data_dir = self.base_dir / "downloads" / video_id
        data_dir.mkdir(parents=True)
        meta_path = data_dir / "meta.json"
        merged_path = data_dir / f"{video_id}_merge.mp4"
        meta_path.write_text(json.dumps({"id": video_id, "title": "Original title"}), encoding="utf-8")
        merged_path.write_bytes(b"merged")
        self.repo.upsert_video(video_id, f"https://www.youtube.com/watch?v={video_id}")
        self.repo.save_media_files(video_id, meta_path=str(meta_path), merged_path=str(merged_path))
        self.repo.update_video_status(video_id, "downloading")
        self.repo.update_video_status(video_id, "downloaded")
        return video_id, data_dir, merged_path

    def _save_ready_draft(self, video_id="abc123def45", tid_source="llm"):
        self.repo.save_publish_draft(
            video_id=video_id,
            platform="bilibili",
            title="中文标题",
            description="中文描述\n\n原视频链接：https://www.youtube.com/watch?v=abc123def45",
            tags=["动画", "测试"],
            tid=27,
            tid_label="动画-综合",
            tid_reason="适合动画分区",
            tid_source=tid_source,
            status="ready",
        )
        self.repo.update_video_status(video_id, "ready_to_publish")

    def test_describe_video_saves_draft_and_updates_status(self):
        video_id, data_dir, _ = self._add_downloaded_video()
        payload = {
            "account": "mybili",
            "video_file": str(data_dir / f"{video_id}_merge.mp4"),
            "title": "中文标题",
            "description": "中文描述\n\n原视频链接：https://www.youtube.com/watch?v=abc123def45",
            "tid": 27,
            "tid_selection": {"tid": 27, "label": "动画-综合", "reason": "适合动画分区", "source": "llm"},
            "tags": ["动画", "测试"],
        }

        with patch("app.publish_service.build_publish_payload", return_value=payload):
            result = describe_video(video_id, self.config)

        video = self.repo.get_video(video_id)
        draft = self.repo.get_publish_draft(video_id, "bilibili")
        job = self.repo.get_latest_job(video_id, "describe")
        self.assertEqual(result["status"], "ready_to_publish")
        self.assertEqual(video["status"], "ready_to_publish")
        self.assertEqual(draft["title"], "中文标题")
        self.assertEqual(draft["tid_source"], "llm")
        self.assertEqual(job["status"], "succeeded")

    def test_publish_video_dry_run_uses_saved_draft(self):
        video_id, _, merged_path = self._add_downloaded_video()
        self._save_ready_draft(video_id)

        result = publish_video(video_id, self.config, dry_run=True)

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["payload"]["video_file"], str(merged_path))
        self.assertEqual(result["payload"]["title"], "中文标题")

    def test_publish_video_saves_record_and_updates_status(self):
        video_id, _, _ = self._add_downloaded_video()
        self._save_ready_draft(video_id)

        with patch("app.publish_service.publish_payload_to_bilibili", side_effect=lambda payload, config, dry_run=False: payload):
            result = publish_video(video_id, self.config)

        records = self.repo.list_publish_records(video_id, "bilibili")
        video = self.repo.get_video(video_id)
        job = self.repo.get_latest_job(video_id, "publish")
        self.assertEqual(result["status"], "published")
        self.assertEqual(video["status"], "published")
        self.assertEqual(records[0]["status"], "published")
        self.assertEqual(job["status"], "succeeded")

    def test_publish_video_blocks_duplicate_publish(self):
        video_id, _, _ = self._add_downloaded_video()
        self._save_ready_draft(video_id)
        self.repo.save_publish_record(video_id, "bilibili", "mybili", "published")

        with self.assertRaises(RuntimeError):
            publish_video(video_id, self.config)

    def test_publish_video_blocks_fallback_tid_for_real_publish(self):
        video_id, _, _ = self._add_downloaded_video()
        self._save_ready_draft(video_id, tid_source="fallback")

        with self.assertRaises(RuntimeError):
            publish_video(video_id, self.config)


if __name__ == "__main__":
    unittest.main()
