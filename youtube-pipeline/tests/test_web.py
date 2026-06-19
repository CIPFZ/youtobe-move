import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.publish_service import update_publish_draft
from app.web import WebError, _handle_action, _handle_batch_action, _list_videos


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pipeline.db"
        self.config = SimpleNamespace(db_path=self.db_path, bilibili_tid_options="27:动画-综合,188:科技")
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

    def test_batch_action_reports_partial_errors(self):
        with patch("app.web.review_publish_draft", side_effect=[{"status": "ok"}, KeyError("missing")]):
            result = _handle_batch_action(
                self.config,
                "approve",
                ["abc123def45", "missing12345"],
                {"note": "batch"},
            )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["results"][0]["video_id"], "abc123def45")

    def test_batch_action_rejects_unsupported_action(self):
        with self.assertRaises(WebError):
            _handle_batch_action(self.config, "publish", ["abc123def45"], {})

    def test_add_url_api_helper_creates_queue_item(self):
        from app.operations import add_video_url

        result = add_video_url("https://www.youtube.com/watch?v=abc123def45", self.config, source="web")
        video = self.repo.get_video("abc123def45")
        job = self.repo.get_latest_job("abc123def45", "download")

        self.assertEqual(result["status"], "created")
        self.assertEqual(video["status"], "selected")
        self.assertEqual(job["status"], "pending")

    def test_update_publish_draft_marks_manual_and_resets_review(self):
        self.repo.upsert_video(
            "abc123def45",
            "https://www.youtube.com/watch?v=abc123def45",
            status="ready_to_publish",
        )
        self.repo.save_publish_draft(
            "abc123def45",
            "bilibili",
            title="Old title",
            description="Old body",
            tags=["old"],
            tid=27,
            tid_source="llm",
            status="approved",
        )

        result = update_publish_draft(
            "abc123def45",
            self.config,
            title="New title",
            description="New body",
            tags="动画, 测试",
            tid=188,
        )

        draft = result["draft"]
        self.assertEqual(draft["title"], "New title")
        self.assertEqual(draft["tid"], 188)
        self.assertEqual(draft["tid_label"], "科技")
        self.assertEqual(draft["tid_source"], "manual")
        self.assertEqual(draft["status"], "pending")
        self.assertEqual(draft["review_note"], "")

    def test_update_publish_draft_rejects_unknown_tid(self):
        self.repo.upsert_video(
            "abc123def45",
            "https://www.youtube.com/watch?v=abc123def45",
            status="ready_to_publish",
        )
        self.repo.save_publish_draft(
            "abc123def45",
            "bilibili",
            title="Old title",
            description="Old body",
            tags=["old"],
            tid=27,
            tid_source="llm",
        )

        with self.assertRaises(ValueError):
            update_publish_draft(
                "abc123def45",
                self.config,
                title="New title",
                description="New body",
                tags=["tag"],
                tid=999,
            )


if __name__ == "__main__":
    unittest.main()
