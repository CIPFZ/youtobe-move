from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from app import api
from app.discovery import repository as repo


def _start_server(monkeypatch, tmp_path):
    db_path = tmp_path / "discovery.db"
    monkeypatch.setattr(api.settings, "discovery_db_path", db_path)
    monkeypatch.setattr(api.settings, "download_media_dir", tmp_path / "downloads")
    monkeypatch.setattr(api.settings, "api_token", "")
    repo.init_db(db_path)
    repo.ensure_video_row(db_path, "abc123def45", "https://youtube.com/watch?v=abc123def45", "manual")
    repo.mark_downloaded(db_path, "abc123def45", "/tmp/abc123def45", 10)

    server = api.run_api_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _post_json(url: str, payload: dict[str, object]):
    return urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def test_pull_lock_release_and_mark_published_http(monkeypatch, tmp_path):
    server, base = _start_server(monkeypatch, tmp_path)

    try:
        req = _post_json(base + "/api/videos/abc123def45/pull-lock", {"locked_by": "local-a", "ttl_minutes": 30})
        with urllib.request.urlopen(req, timeout=5) as resp:
            locked = json.loads(resp.read().decode("utf-8"))
        assert locked["ok"] is True
        assert locked["data"]["status"] == "pulling"
        assert locked["data"]["pull_locked_by"] == "local-a"

        req = _post_json(base + "/api/videos/abc123def45/pull-lock", {"locked_by": "local-b"})
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as resp:
            conflict = json.loads(resp.read().decode("utf-8"))
            assert resp.status == 409
            assert conflict["error"]["code"] == "pull_lock_conflict"
        else:
            raise AssertionError("Expected pull lock conflict")

        req = _post_json(base + "/api/videos/abc123def45/release-pull-lock", {"locked_by": "local-a"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            released = json.loads(resp.read().decode("utf-8"))
        assert released["data"]["status"] == "downloaded"

        req = _post_json(base + "/api/videos/abc123def45/mark-published", {"platform": "bilibili", "publish_ref": "BV123"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            published = json.loads(resp.read().decode("utf-8"))
        assert published["ok"] is True
        assert published["data"]["status"] == "published"
        assert published["data"]["publish_platform"] == "bilibili"
        assert published["data"]["publish_ref"] == "BV123"
    finally:
        server.shutdown()
        server.server_close()

