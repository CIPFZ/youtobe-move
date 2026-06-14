import sqlite3
from datetime import datetime, timedelta, timezone

from app.discovery.models import VideoCandidate
from app.discovery import repository as repo
from app.download_service import make_progress_callback


def test_repository_schema_and_status_flow(tmp_path):
    db_path = tmp_path / "discovery.db"
    repo.init_db(db_path)

    with sqlite3.connect(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(videos)")}

    assert "videos" in tables
    assert "discovered_videos" not in tables
    assert "status" in columns
    assert "download_status" not in columns
    assert "language_hint" not in columns
    assert "comment_count" not in columns
    assert "like_count" not in columns
    assert "task_id" in columns
    assert "download_progress" in columns
    assert "download_attempts" in columns
    assert "last_error_at" in columns
    assert "score_json" in columns

    item = VideoCandidate(
        video_id="abc123def45",
        url="https://www.youtube.com/watch?v=abc123def45",
        title="demo",
        channel_title="channel",
        published_at="2026-06-14T00:00:00+00:00",
        duration_sec=120,
        view_count=10000,
        keyword="funny cats",
        category="pets",
        score=7.5,
        raw_json="{}",
        score_json='{"score_total": 7.5}',
    )
    assert repo.upsert_candidates(db_path, [item]) == 1
    assert repo.count_videos(db_path, download_status="pending") == 1

    pending = repo.get_pending_downloads(db_path, min_score=5.0)
    assert [row["video_id"] for row in pending] == ["abc123def45"]

    repo.mark_downloading(db_path, "abc123def45", task_id=42)
    repo.mark_downloaded(db_path, "abc123def45", "/tmp/video-dir", 123, "/tmp/thumb.jpg", "/tmp/meta.json", task_id=42)

    downloaded = repo.get_video_by_id(db_path, "abc123def45")
    assert downloaded["status"] == "downloaded"
    assert downloaded["download_status"] == "downloaded"
    assert downloaded["file_dir"] == "/tmp/video-dir"
    assert downloaded["file_path"] == "/tmp/video-dir"
    assert downloaded["thumbnail_path"] == "/tmp/thumb.jpg"
    assert downloaded["meta_path"] == "/tmp/meta.json"
    assert downloaded["task_id"] == 42
    assert downloaded["download_progress"] == 100
    assert downloaded["download_attempts"] == 1
    assert downloaded["score_json"] == '{"score_total": 7.5}'

    repo.mark_pulled(db_path, "abc123def45")
    pulled = repo.get_video_by_id(db_path, "abc123def45")
    assert pulled["status"] == "pulled"
    assert pulled["file_dir"] == ""
    assert pulled["file_size"] == 0

    events = repo.list_video_events(db_path, "abc123def45")
    assert [event["event_type"] for event in events] == ["downloading", "downloaded", "pulled"]
    assert events[0]["task_id"] == 42

    assert repo.count_video_events(db_path, "abc123def45", task_id=42) == 2
    paged = repo.list_video_events(db_path, "abc123def45", task_id=42, limit=1, offset=1)
    assert [event["event_type"] for event in paged] == ["downloaded"]


def test_progress_callback_updates_video_progress_and_events(tmp_path):
    db_path = tmp_path / "discovery.db"
    repo.init_db(db_path)
    repo.ensure_video_row(db_path, "progressvid", "https://youtube.com/watch?v=progressvid", "manual")
    repo.mark_downloading(db_path, "progressvid", task_id=7)

    callback = make_progress_callback(db_path, "progressvid", task_id=7)
    callback({"stream": "video", "status": "downloading", "progress": 10.0})
    callback({"stream": "video", "status": "downloading", "progress": 12.0})
    callback({"stream": "audio", "status": "finished", "progress": 55.0})

    video = repo.get_video_by_id(db_path, "progressvid")
    assert video["download_progress"] == 55.0

    events = repo.list_video_events(db_path, "progressvid")
    progress_events = [event for event in events if event["event_type"] == "progress"]
    assert [event["data"]["progress"] for event in progress_events] == [10.0, 55.0]


def test_repository_list_filters_by_status_category_and_score(tmp_path):
    db_path = tmp_path / "discovery.db"
    repo.init_db(db_path)
    repo.upsert_candidates(
        db_path,
        [
            VideoCandidate("v1", "u1", "t1", "c", "", 100, 1000, "kw", "pets", 4.0, "{}"),
            VideoCandidate("v2", "u2", "t2", "c", "", 100, 1000, "kw", "funny", 8.0, "{}"),
        ],
    )
    repo.mark_downloading(db_path, "v2")
    repo.mark_downloaded(db_path, "v2", "/tmp/v2", 10)

    rows = repo.list_videos(db_path, category="funny", download_status="downloaded", min_score=5.0)

    assert len(rows) == 1
    assert rows[0]["video_id"] == "v2"


def test_pull_lock_release_expiry_and_published_flow(tmp_path):
    db_path = tmp_path / "discovery.db"
    repo.init_db(db_path)
    repo.ensure_video_row(db_path, "lockvid1234", "https://youtube.com/watch?v=lockvid1234", "manual")
    repo.mark_downloaded(db_path, "lockvid1234", "/tmp/lockvid1234", 10)

    locked = repo.acquire_pull_lock(db_path, "lockvid1234", locked_by="local-a", ttl_minutes=30)
    assert locked["status"] == "pulling"
    assert locked["pull_locked_by"] == "local-a"
    assert locked["pull_lock_expires_at"]

    conflict = repo.acquire_pull_lock(db_path, "lockvid1234", locked_by="local-b", ttl_minutes=30)
    assert conflict["status"] == "pulling"
    assert conflict["pull_locked_by"] == "local-a"

    still_locked = repo.release_pull_lock(db_path, "lockvid1234", locked_by="local-b")
    assert still_locked["status"] == "pulling"
    released = repo.release_pull_lock(db_path, "lockvid1234", locked_by="local-a")
    assert released["status"] == "downloaded"
    assert released["pull_locked_by"] == ""

    repo.acquire_pull_lock(db_path, "lockvid1234", locked_by="local-a", ttl_minutes=30)
    expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE videos SET pull_lock_expires_at=? WHERE video_id=?",
            (expired_at, "lockvid1234"),
        )
    assert repo.reset_expired_pull_locks(db_path) == 1
    expired = repo.get_video_by_id(db_path, "lockvid1234")
    assert expired["status"] == "downloaded"
    assert expired["pull_locked_by"] == ""

    published = repo.mark_published(db_path, "lockvid1234", platform="bilibili", publish_ref="BV123")
    assert published["status"] == "published"
    assert published["publish_platform"] == "bilibili"
    assert published["publish_ref"] == "BV123"
