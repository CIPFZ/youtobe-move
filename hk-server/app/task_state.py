from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
_state: dict[str, Any] = {
    "running": False,
    "task_name": "",
    "started_at": "",
    "last_finished_at": "",
    "last_summary": {},
    "last_error": "",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def try_start_task(name: str) -> bool:
    """Mark a background task as running if none is active."""
    with _lock:
        if _state["running"]:
            return False
        _state.update(
            {
                "running": True,
                "task_name": name,
                "started_at": _now(),
                "last_error": "",
            }
        )
        return True


def finish_task(summary: dict[str, Any] | None = None, error: str = "") -> None:
    """Finish the active task and preserve its result for inspection."""
    with _lock:
        _state.update(
            {
                "running": False,
                "task_name": "",
                "started_at": "",
                "last_finished_at": _now(),
                "last_summary": summary or {},
                "last_error": str(error or ""),
            }
        )


def get_task_state() -> dict[str, Any]:
    with _lock:
        return dict(_state)
