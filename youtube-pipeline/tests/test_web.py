import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.web import WebError, _handle_action, _list_videos


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pipeline.db"
        self.config = SimpleNamespace(db_path=self.db_path)
        self.conn = connect(self.db_path)
        init_schema(self.conn)
        self.repo = Repository(self.conn)
        self.addCleanup(self.conn.close)
        self.addCleanup(self.temp_dir.cleanup)

    def test_list_videos_includes_draft_and_jobs(self):
        self.repo.upsert_video(
            "abc123def45",
            "https://www.youtube.com/watch?v=abc123def45",
            title="Original title",
            status="ready_to_publish",
        )
        self.repo.save_publish_draft(
            "abc123def45",
            "bilibili",
            title="Draft title",
            description="Draft body",
            tags=["tag"],
            tid=47,
            tid_source="llm",
        )
        self.repo.create_job("download", video_id="abc123def45", status="succeeded")

        result = _list_videos(self.config, {"status": ["ready_to_publish"]})

        self.assertEqual(len(result["videos"]), 1)
        row = result["videos"][0]
        self.assertEqual(row["video"]["video_id"], "abc123def45")
        self.assertEqual(row["publish_draft"]["title"], "Draft title")
        self.assertEqual(row["latest_download_job"]["status"], "succeeded")

    def test_real_publish_requires_confirm(self):
        with self.assertRaises(WebError) as ctx:
            _handle_action(self.config, "abc123def45", "publish", {})

        self.assertIn("confirm=true", ctx.exception.message)

    def test_publish_dry_run_delegates_to_publish_service(self):
        with patch("app.web.publish_video", return_value={"status": "dry_run"}) as publish_video:
            result = _handle_action(self.config, "abc123def45", "publish-dry-run", {})

        self.assertEqual(result["status"], "dry_run")
        publish_video.assert_called_once_with("abc123def45", self.config, dry_run=True, force=False)


if __name__ == "__main__":
    unittest.main()
