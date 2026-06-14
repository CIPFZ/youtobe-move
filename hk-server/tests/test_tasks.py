import sqlite3

from app import tasks


def test_task_lifecycle_and_event_listing(tmp_path):
    db_path = tmp_path / "tasks.db"
    first = tasks.start_task(db_path, "discovery_download", {"source": "test"})
    assert first is not None
    assert first["status"] == "running"
    assert first["input"] == {"source": "test"}

    assert tasks.start_task(db_path, "manual_download") is None

    tasks.record_task_event(db_path, first["task_id"], "step", "did work", {"count": 1})
    tasks.finish_task(db_path, first["task_id"], summary={"downloaded": 2})

    finished = tasks.get_task(db_path, first["task_id"])
    assert finished["status"] == "success"
    assert finished["summary"] == {"downloaded": 2}
    assert finished["error"] == ""

    events = tasks.list_task_events(db_path, first["task_id"])
    assert [event["event_type"] for event in events] == ["started", "step", "finished"]
    assert events[1]["data"] == {"count": 1}

    second = tasks.start_task(db_path, "manual_download", {"video_id": "abc123def45"})
    assert second is not None
    tasks.finish_task(db_path, second["task_id"], error="boom")
    assert tasks.get_task(db_path, second["task_id"])["status"] == "failed"
    assert tasks.count_tasks(db_path, status="failed") == 1
    assert [item["task_id"] for item in tasks.list_tasks(db_path, task_name="manual_download")] == [second["task_id"]]


def test_recover_interrupted_tasks_marks_active_tasks_failed(tmp_path):
    db_path = tmp_path / "tasks.db"
    task = tasks.start_task(db_path, "discovery_download")
    assert task is not None

    recovered = tasks.recover_interrupted_tasks(db_path)

    assert recovered == 1
    restored = tasks.get_task(db_path, task["task_id"])
    assert restored["status"] == "failed"
    assert restored["error"] == "Task interrupted by service restart"
    assert tasks.get_running_task(db_path) is None

    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT event_type FROM task_events WHERE task_id=? ORDER BY event_id DESC LIMIT 1", (task["task_id"],)).fetchone()
    assert row[0] == "failed"


def test_request_cancel_marks_active_task_and_finish_becomes_cancelled(tmp_path):
    db_path = tmp_path / "tasks.db"
    task = tasks.start_task(db_path, "manual_download")
    assert task is not None

    cancelled = tasks.request_cancel(db_path, task["task_id"])

    assert cancelled["status"] == "cancel_requested"
    assert tasks.is_cancel_requested(db_path, task["task_id"])

    tasks.finish_task(db_path, task["task_id"], summary={"cancelled": True})
    finished = tasks.get_task(db_path, task["task_id"])
    assert finished["status"] == "cancelled"
    assert tasks.get_running_task(db_path) is None
