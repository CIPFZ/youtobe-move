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

    def test_list_videos_filters_by_draft_status_and_error_type(self):
        self.repo.upsert_video(
            "abc123def45",
            "https://www.youtube.com/watch?v=abc123def45",
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
            status="approved",
        )
        job_id = self.repo.create_job("publish", video_id="abc123def45")
        self.repo.update_job_status(job_id, "failed", error="publish failed", error_type="publish_failed")

        matched = _list_videos(self.config, {"draft_status": ["approved"], "error_type": ["publish_failed"]})
        missed = _list_videos(self.config, {"draft_status": ["pending"], "error_type": ["publish_failed"]})

        self.assertEqual(len(matched["videos"]), 1)
        self.assertEqual(len(missed["videos"]), 0)

    def test_real_publish_requires_confirm(self):
        with self.assertRaises(WebError) as ctx:
            _handle_action(self.config, "abc123def45", "publish", {})

        self.assertIn("confirm=true", ctx.exception.message)

    def test_publish_dry_run_delegates_to_publish_service(self):
        with patch("app.web.publish_video", return_value={"status": "dry_run"}) as publish_video:
            result = _handle_action(self.config, "abc123def45", "publish-dry-run", {})

        self.assertEqual(result["status"], "dry_run")
        publish_video.assert_called_once_with("abc123def45", self.config, dry_run=True, force=False)

    def test_approve_delegates_to_review_service(self):
        with patch("app.web.review_publish_draft", return_value={"status": "ok"}) as review_publish_draft:
            result = _handle_action(self.config, "abc123def45", "approve", {"note": "ok"})

        self.assertEqual(result["status"], "ok")
        review_publish_draft.assert_called_once_with("abc123def45", self.config, "approved", note="ok")

    def test_add_url_api_helper_creates_queue_item(self):
        from app.operations import add_video_url

        result = add_video_url("https://www.youtube.com/watch?v=abc123def45", self.config, source="web")
        video = self.repo.get_video("abc123def45")
        job = self.repo.get_latest_job("abc123def45", "download")

        self.assertEqual(result["status"], "created")
        self.assertEqual(video["status"], "selected")
        self.assertEqual(job["status"], "pending")


if __name__ == "__main__":
    unittest.main()
