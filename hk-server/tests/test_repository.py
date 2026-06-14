import sqlite3

from app.discovery.models import VideoCandidate
from app.discovery import repository as repo


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

    repo.mark_pulled(db_path, "abc123def45")
    pulled = repo.get_video_by_id(db_path, "abc123def45")
    assert pulled["status"] == "pulled"
    assert pulled["file_dir"] == ""
    assert pulled["file_size"] == 0

    events = repo.list_video_events(db_path, "abc123def45")
    assert [event["event_type"] for event in events] == ["downloading", "downloaded", "pulled"]
    assert events[0]["task_id"] == 42


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
