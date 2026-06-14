import sqlite3

from app.discovery import repository as repo
from app.disk_cleaner import cleanup_if_needed


def test_cleanup_expires_old_download_and_deletes_files(tmp_path):
    db_path = tmp_path / "discovery.db"
    media_dir = tmp_path / "downloads"
    video_dir = media_dir / "pets" / "oldvideo"
    video_dir.mkdir(parents=True)
    (video_dir / "oldvideo.mp4").write_bytes(b"x" * 10)

    repo.init_db(db_path)
    repo.ensure_video_row(db_path, "oldvideo", "https://youtube.com/watch?v=oldvideo", "pets")
    repo.mark_downloading(db_path, "oldvideo")
    repo.mark_downloaded(db_path, "oldvideo", str(video_dir), 10)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE videos SET downloaded_at = datetime('now', '-10 days') WHERE video_id = ?",
            ("oldvideo",),
        )

    deleted = cleanup_if_needed(db_path, media_dir, max_gb=50.0, max_days=7)

    assert deleted == 1
    assert not video_dir.exists()
    row = repo.get_video_by_id(db_path, "oldvideo")
    assert row["status"] == "expired"
    assert row["file_dir"] == ""
    assert row["file_size"] == 0


def test_cleanup_expires_missing_overflow_record(tmp_path):
    db_path = tmp_path / "discovery.db"
    media_dir = tmp_path / "downloads"

    repo.init_db(db_path)
    repo.ensure_video_row(db_path, "missingfile", "https://youtube.com/watch?v=missingfile", "pets")
    repo.mark_downloading(db_path, "missingfile")
    repo.mark_downloaded(db_path, "missingfile", str(media_dir / "missingfile"), 1024)

    deleted = cleanup_if_needed(db_path, media_dir, max_gb=0.0000001, max_days=30)

    assert deleted == 1
    assert repo.get_video_by_id(db_path, "missingfile")["status"] == "expired"
