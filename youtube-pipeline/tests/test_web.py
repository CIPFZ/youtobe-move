import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.publish_service import update_publish_draft
from app.web import WebError, _handle_action, _handle_batch_action, _list_events, _list_videos, _status_settings


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

    def test_list_events_filters_by_module_and_paginates(self):
        self.repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        self.repo.create_event("abc123def45", None, "worker", "worker_run_started", "started")
        self.repo.create_event("abc123def45", None, "core", "video_status_changed", "changed")
        self.repo.create_event("abc123def45", None, "worker", "worker_run_finished", "finished")
        self.conn.commit()

        first_page = _list_events(self.config, {"module": ["worker"], "limit": ["1"], "offset": ["0"]})
        second_page = _list_events(self.config, {"module": ["worker"], "limit": ["1"], "offset": ["1"]})

        self.assertEqual(first_page["events"][0]["event_type"], "worker_run_finished")
        self.assertTrue(first_page["has_more"])
        self.assertEqual(second_page["events"][0]["event_type"], "worker_run_started")
        self.assertEqual(second_page["module"], "worker")

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

    def test_status_settings_includes_worker_controls(self):
        self.config.pipeline_enabled = True
        self.config.publish_mode = "approved_auto"
        self.config.worker_interval_seconds = 60
        self.config.worker_cron = ""
        self.config.worker_enable_discovery = True
        self.config.worker_enable_download = True
        self.config.worker_enable_describe = True
        self.config.worker_enable_publish = False
        self.config.worker_publish_dry_run = True
        self.config.worker_discovery_min_queue_size = 3
        self.config.worker_discovery_source = None
        self.config.job_lease_seconds = 1800
        self.config.publish_min_interval_seconds = 600
        self.config.publish_daily_limit = 5
        self.config.publish_window_start = "09:00"
        self.config.publish_window_end = "23:00"

        settings = _status_settings(self.config)

        self.assertTrue(settings["pipeline_enabled"])
        self.assertFalse(settings["worker_enable_publish"])
        self.assertEqual(settings["worker_interval_seconds"], 60)
        self.assertEqual(settings["worker_discovery_min_queue_size"], 3)

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

    def test_update_publish_draft_rejects_too_long_title(self):
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
                title="T" * 81,
                description="New body",
                tags=["tag"],
                tid=27,
            )

    def test_update_publish_draft_rejects_too_long_description(self):
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
                description="D" * 2001,
                tags=["tag"],
                tid=27,
            )

    def test_update_publish_draft_rejects_too_many_tags(self):
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
                tags=[f"tag{i}" for i in range(9)],
                tid=27,
            )

    def test_update_publish_draft_rejects_too_long_tag(self):
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
                tags=["x" * 21],
                tid=27,
            )


if __name__ == "__main__":
    unittest.main()
