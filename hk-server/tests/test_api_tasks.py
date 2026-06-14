import json
import threading
import urllib.request

from app import api, tasks
from app.discovery import repository as repo


def test_task_list_and_detail_http(monkeypatch, tmp_path):
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(api.settings, "discovery_db_path", db_path)
    monkeypatch.setattr(api.settings, "download_media_dir", tmp_path / "downloads")
    monkeypatch.setattr(api.settings, "api_token", "")

    task = tasks.start_task(db_path, "manual_download", {"video_id": "abc123def45"})
    tasks.record_task_event(db_path, task["task_id"], "step", "testing")
    tasks.finish_task(db_path, task["task_id"], summary={"downloaded": True})

    server = api.run_api_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        with urllib.request.urlopen(base + "/api/tasks?type=manual_download", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert body["ok"] is True
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["task_id"] == task["task_id"]
        assert body["data"]["current"]["running"] is False

        with urllib.request.urlopen(base + f"/api/tasks/{task['task_id']}", timeout=5) as resp:
            detail = json.loads(resp.read().decode("utf-8"))
        assert detail["ok"] is True
        assert detail["data"]["status"] == "success"
        assert [event["event_type"] for event in detail["data"]["events"]] == ["started", "step", "finished"]
    finally:
        server.shutdown()
        server.server_close()


def test_task_cancel_retry_and_video_events_http(monkeypatch, tmp_path):
    db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(api.settings, "discovery_db_path", db_path)
    monkeypatch.setattr(api.settings, "download_media_dir", tmp_path / "downloads")
    monkeypatch.setattr(api.settings, "api_token", "")

    running = tasks.start_task(
        db_path,
        "manual_download",
        {"video_id": "abc123def45", "url": "https://youtube.com/watch?v=abc123def45", "category": "manual"},
    )
    repo.init_db(db_path)
    repo.ensure_video_row(db_path, "abc123def45", "https://youtube.com/watch?v=abc123def45", "manual")
    repo.mark_downloading(db_path, "abc123def45", task_id=running["task_id"])
    repo.mark_download_failed(db_path, "abc123def45", "failed", task_id=running["task_id"])
    tasks.finish_task(db_path, running["task_id"], error="failed")

    retry_called = {}

    def fake_start_manual(self, *, url, category, vid, input_data):
        retry_called["input"] = input_data
        api._success_response(self, {"started": True, "task_id": 999, "status": "running", "video_id": vid})

    monkeypatch.setattr(api._ApiHandler, "_start_manual_download", fake_start_manual)

    server = api.run_api_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        active = tasks.start_task(db_path, "discovery_download")
        req = urllib.request.Request(base + f"/api/tasks/{active['task_id']}/cancel", method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            cancel_body = json.loads(resp.read().decode("utf-8"))
        assert cancel_body["ok"] is True
        assert cancel_body["data"]["status"] == "cancel_requested"
        tasks.finish_task(db_path, active["task_id"], summary={"cancelled": True})

        req = urllib.request.Request(base + f"/api/tasks/{running['task_id']}/retry", method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            retry_body = json.loads(resp.read().decode("utf-8"))
        assert retry_body["data"]["task_id"] == 999
        assert retry_called["input"]["retry_of"] == running["task_id"]

        with urllib.request.urlopen(base + "/api/videos/abc123def45/events", timeout=5) as resp:
            events_body = json.loads(resp.read().decode("utf-8"))
        assert events_body["ok"] is True
        assert [event["event_type"] for event in events_body["data"]["items"]] == ["downloading", "failed"]
    finally:
        server.shutdown()
        server.server_close()
