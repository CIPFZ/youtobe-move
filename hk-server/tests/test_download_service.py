from pathlib import Path

from app import download_service, task_state
from app.discovery import repository as repo


def setup_service(monkeypatch, tmp_path):
    monkeypatch.setattr(download_service.settings, "discovery_db_path", tmp_path / "discovery.db")
    monkeypatch.setattr(download_service.settings, "download_media_dir", tmp_path / "downloads")
    monkeypatch.setattr(download_service.settings, "disk_max_storage_gb", 50.0)
    monkeypatch.setattr(download_service.settings, "disk_max_retention_days", 30)
    monkeypatch.setattr(download_service.settings, "disk_min_free_gb", 0.0)
    task_state._current_task_id = None


def test_run_manual_download_success(monkeypatch, tmp_path):
    setup_service(monkeypatch, tmp_path)

    def fake_download_media(url, out_dir, **kwargs):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "abc123def45.mp4").write_bytes(b"video")
        (out_dir / "abc123def45.m4a").write_bytes(b"audio")
        return {"thumbnail_path": Path("")}

    monkeypatch.setattr(download_service, "download_media", fake_download_media)
    monkeypatch.setattr(download_service, "cleanup_if_needed", lambda **kwargs: 0)

    task = task_state.try_start_task("manual_download", {"video_id": "abc123def45"})
    assert task is not None
    summary = download_service.run_manual_download(
        url="https://youtube.com/watch?v=abc123def45",
        category="manual",
        video_id="abc123def45",
    )

    assert summary["downloaded"] is True
    video = repo.get_video_by_id(download_service.settings.discovery_db_path, "abc123def45")
    assert video["status"] == "downloaded"
    assert video["download_progress"] == 100
    assert video["task_id"] == task["task_id"]
    assert task_state.get_task_state()["running"] is False


def test_run_manual_download_failure_marks_video_failed(monkeypatch, tmp_path):
    setup_service(monkeypatch, tmp_path)

    def fake_download_media(url, out_dir, **kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr(download_service, "download_media", fake_download_media)

    task = task_state.try_start_task("manual_download", {"video_id": "abc123def45"})
    assert task is not None
    summary = download_service.run_manual_download(
        url="https://youtube.com/watch?v=abc123def45",
        category="manual",
        video_id="abc123def45",
    )

    assert summary["downloaded"] is False
    video = repo.get_video_by_id(download_service.settings.discovery_db_path, "abc123def45")
    assert video["status"] == "failed"
    assert "download failed" in video["error"]
    state = task_state.get_task_state()
    assert state["running"] is False
    assert "download failed" in state["last_error"]


def test_run_manual_download_stops_when_disk_free_space_is_low(monkeypatch, tmp_path):
    setup_service(monkeypatch, tmp_path)
    monkeypatch.setattr(download_service.settings, "disk_min_free_gb", 10.0)
    monkeypatch.setattr(
        download_service.shutil,
        "disk_usage",
        lambda path: download_service.shutil._ntuple_diskusage(total=20, used=19, free=1),
    )

    called = {"download": False}

    def fake_download_media(url, out_dir, **kwargs):
        called["download"] = True
        return {}

    monkeypatch.setattr(download_service, "download_media", fake_download_media)

    task = task_state.try_start_task("manual_download", {"video_id": "abc123def45"})
    assert task is not None
    summary = download_service.run_manual_download(
        url="https://youtube.com/watch?v=abc123def45",
        category="manual",
        video_id="abc123def45",
    )

    assert summary["downloaded"] is False
    assert called["download"] is False
    video = repo.get_video_by_id(download_service.settings.discovery_db_path, "abc123def45")
    assert video["status"] == "failed"
    assert "Insufficient disk space" in video["error"]
    assert "Insufficient disk space" in task_state.get_task_state()["last_error"]
