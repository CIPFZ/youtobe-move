import json
import threading
import urllib.request

from app import api, tasks


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
