from __future__ import annotations

import json
import threading
import urllib.request

from app import api
from app.discovery import repository as repo


def _start_server(monkeypatch, tmp_path):
    db_path = tmp_path / "discovery.db"
    download_dir = tmp_path / "downloads"
    monkeypatch.setattr(api.settings, "discovery_db_path", db_path)
    monkeypatch.setattr(api.settings, "download_media_dir", download_dir)
    monkeypatch.setattr(api.settings, "api_token", "")
    monkeypatch.setattr(api.settings, "disk_max_storage_gb", 50.0)
    monkeypatch.setattr(api.settings, "disk_max_retention_days", 30)
    repo.init_db(db_path)
    server = api.run_api_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", db_path, download_dir


def _post_json(url: str, payload: dict[str, object]):
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def test_metrics_and_admin_disk_http(monkeypatch, tmp_path):
    server, base, db_path, _download_dir = _start_server(monkeypatch, tmp_path)
    repo.ensure_video_row(db_path, "abc123def45", "https://youtube.com/watch?v=abc123def45", "manual")
    repo.mark_download_failed(db_path, "abc123def45", "boom")

    try:
        with urllib.request.urlopen(base + "/api/metrics", timeout=5) as resp:
            metrics = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "text/plain" in resp.headers["Content-Type"]
        assert 'hk_server_videos_total{status="failed"} 1' in metrics
        assert "hk_server_disk_free_bytes" in metrics
        assert "hk_server_task_running 0" in metrics

        with urllib.request.urlopen(base + "/api/admin/disk", timeout=5) as resp:
            disk = json.loads(resp.read().decode("utf-8"))
        assert disk["ok"] is True
        assert disk["data"]["disk_free_bytes"] > 0
        assert disk["data"]["downloaded_bytes"] == 0
    finally:
        server.shutdown()
        server.server_close()


def test_admin_cleanup_run_http(monkeypatch, tmp_path):
    server, base, db_path, download_dir = _start_server(monkeypatch, tmp_path)
    video_dir = download_dir / "manual" / "cleanupvid1"
    video_dir.mkdir(parents=True)
    (video_dir / "cleanupvid1.mp4").write_bytes(b"x" * 1024)
    repo.ensure_video_row(db_path, "cleanupvid1", "https://youtube.com/watch?v=cleanupvid1", "manual")
    repo.mark_downloaded(db_path, "cleanupvid1", str(video_dir), 1024)

    try:
        req = _post_json(base + "/api/admin/cleanup/run", {"max_gb": 0.0000001, "max_days": 30})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["ok"] is True
        assert body["data"]["expired"] == 1
        video = repo.get_video_by_id(db_path, "cleanupvid1")
        assert video["status"] == "expired"
        assert not video_dir.exists()
    finally:
        server.shutdown()
        server.server_close()

