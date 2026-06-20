import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_list_videos_with_media_files_filters_statuses(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45", status="selected")
        repo.save_media_files("abc123def45", merged_path="runtime/downloads/abc123def45/abc123def45_merge.mp4")
        repo.upsert_video("def123abc45", "https://www.youtube.com/watch?v=def123abc45", status="failed")
        repo.save_media_files("def123abc45", merged_path="runtime/downloads/def123abc45/def123abc45_merge.mp4")

        rows = repo.list_videos_with_media_files(statuses={"failed"})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_id"], "def123abc45")
        self.assertTrue(rows[0]["merged_path"].endswith("def123abc45_merge.mp4"))

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

    def test_claim_pending_job_sets_lock_and_blocks_second_worker(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        job_id = repo.create_job("download", video_id="abc123def45")

        claimed = repo.claim_pending_job("download", "worker-a", lease_seconds=1800)
        second = repo.claim_pending_job("download", "worker-b", lease_seconds=1800)

        self.assertEqual(claimed["id"], job_id)
        self.assertEqual(claimed["lock_owner"], "worker-a")
        self.assertTrue(claimed["locked_at"])
        self.assertIsNone(second)

    def test_concurrent_workers_do_not_claim_duplicate_jobs(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / "pipeline.db"
        self.addCleanup(temp_dir.cleanup)
        job_count = 12
        worker_count = 6
        with connect(db_path) as conn:
            init_schema(conn)
            repo = Repository(conn)
            for index in range(job_count):
                video_id = f"abc123d{index:04d}"
                repo.upsert_video(video_id, f"https://www.youtube.com/watch?v={video_id}", status="selected")
                repo.create_job("download", video_id=video_id)
            conn.commit()

        def claim_jobs(worker_id: str) -> list[int]:
            claimed_ids: list[int] = []
            with connect(db_path) as conn:
                init_schema(conn)
                repo = Repository(conn)
                for _ in range(job_count * 2):
                    claimed = repo.claim_pending_job("download", worker_id, lease_seconds=1800)
                    if claimed:
                        claimed_ids.append(int(claimed["id"]))
                    else:
                        time.sleep(0.005)
            return claimed_ids

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(lambda index: claim_jobs(f"worker-{index}"), range(worker_count)))

        claimed_job_ids = [job_id for worker_result in results for job_id in worker_result]
        self.assertEqual(len(claimed_job_ids), job_count)
        self.assertEqual(len(set(claimed_job_ids)), job_count)

    def test_recover_stale_running_job_restores_video_and_job(self):
        repo = self._repo()
        repo.upsert_video("abc123def45", "https://www.youtube.com/watch?v=abc123def45")
        job_id = repo.create_job("download", video_id="abc123def45")
        claimed = repo.claim_pending_job("download", "worker-a", lease_seconds=1800)
        repo.update_job_status(int(claimed["id"]), "running")
        repo.update_video_status("abc123def45", "downloading")
        repo.conn.execute(
            "UPDATE jobs SET locked_at='2000-01-01 00:00:00', lock_owner='worker-a' WHERE id=?",
            (job_id,),
        )
        repo.conn.commit()

        result = repo.recover_stale_jobs("worker-b", lease_seconds=1800)
        job = repo.get_job(job_id)
        video = repo.get_video("abc123def45")

        self.assertEqual(result["count"], 1)
        self.assertEqual(job["status"], "pending")
        self.assertIsNone(job["locked_at"])
        self.assertEqual(job["lock_owner"], "")
        self.assertEqual(video["status"], "selected")


if __name__ == "__main__":
    unittest.main()
