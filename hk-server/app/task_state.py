import threading
from typing import Any

from app.settings import settings
from app.tasks import (
    finish_task as finish_persisted_task,
    get_latest_finished_task,
    get_running_task,
    init_task_db,
    is_cancel_requested,
    record_task_event as record_persisted_task_event,
    start_task,
)

_lock = threading.Lock()
_current_task_id: int | None = None


def try_start_task(name: str, input_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Create a persisted running task if none is active."""
    global _current_task_id
    db_path = settings.discovery_db_path.resolve()
    init_task_db(db_path)
    with _lock:
        task = start_task(db_path, name, input_data=input_data)
        if task is None:
            return None
        _current_task_id = int(task["task_id"])
        return task


def finish_task(summary: dict[str, Any] | None = None, error: str = "") -> None:
    """Finish the active task and preserve its result for inspection."""
    global _current_task_id
    db_path = settings.discovery_db_path.resolve()
    init_task_db(db_path)
    with _lock:
        task_id = _current_task_id
        if task_id is None:
            running = get_running_task(db_path)
            task_id = int(running["task_id"]) if running else None
        if task_id is not None:
            finish_persisted_task(db_path, task_id, summary=summary, error=error)
        _current_task_id = None


def record_task_event(event_type: str, message: str = "", data: dict[str, Any] | None = None) -> None:
    db_path = settings.discovery_db_path.resolve()
    task_id = _current_task_id
    if task_id is None:
        running = get_running_task(db_path)
        task_id = int(running["task_id"]) if running else None
    if task_id is not None:
        record_persisted_task_event(db_path, task_id, event_type, message, data)


def get_current_task_id() -> int | None:
    task_id = _current_task_id
    if task_id is not None:
        return task_id
    running = get_running_task(settings.discovery_db_path.resolve())
    return int(running["task_id"]) if running else None


def is_current_task_cancel_requested() -> bool:
    task_id = get_current_task_id()
    if task_id is None:
        return False
    return is_cancel_requested(settings.discovery_db_path.resolve(), task_id)


def get_task_state() -> dict[str, Any]:
    db_path = settings.discovery_db_path.resolve()
    init_task_db(db_path)
    running = get_running_task(db_path)
    latest = get_latest_finished_task(db_path)
    if running is not None:
        return {
            "running": True,
            "task_id": running["task_id"],
            "task_name": running["task_name"],
            "started_at": running["started_at"],
            "last_finished_at": latest["finished_at"] if latest else "",
            "last_summary": latest["summary"] if latest else {},
            "last_error": latest["error"] if latest else "",
        }
    return {
        "running": False,
        "task_id": None,
        "task_name": "",
        "started_at": "",
        "last_finished_at": latest["finished_at"] if latest else "",
        "last_summary": latest["summary"] if latest else {},
        "last_error": latest["error"] if latest else "",
    }
