from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ACTIVE_STATUSES = ("pending", "running", "cancel_requested")
RUNNING_STATUSES = ("pending", "running")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _json_loads(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def init_task_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                status TEXT NOT NULL,
                input_json TEXT NOT NULL DEFAULT '{}',
                summary_json TEXT NOT NULL DEFAULT '{}',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_name ON tasks(task_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                data_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_task_events_task_id ON task_events(task_id)")


def _task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["input"] = _json_loads(data.pop("input_json", "{}"))
    data["summary"] = _json_loads(data.pop("summary_json", "{}"))
    return data


def start_task(db_path: Path, task_name: str, input_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    init_task_db(db_path)
    now = _now()
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT task_id FROM tasks WHERE status IN ('pending', 'running', 'cancel_requested') LIMIT 1"
        ).fetchone()
        if active is not None:
            conn.rollback()
            return None
        cur = conn.execute(
            """
            INSERT INTO tasks (task_name, status, input_json, created_at, started_at)
            VALUES (?, 'running', ?, ?, ?)
            """,
            (task_name, _json_dumps(input_data), now, now),
        )
        task_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO task_events (task_id, event_type, message, created_at)
            VALUES (?, 'started', ?, ?)
            """,
            (task_id, f"Task started: {task_name}", now),
        )
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    return _task_from_row(row)


def finish_task(
    db_path: Path,
    task_id: int,
    *,
    summary: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    init_task_db(db_path)
    now = _now()
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        current_status = str(row[0]) if row else ""
        status = "failed" if error else "cancelled" if current_status == "cancel_requested" else "success"
        event_type = "failed" if error else "cancelled" if status == "cancelled" else "finished"
        message = str(error or ("Task cancelled" if status == "cancelled" else "Task finished"))[:2000]
        conn.execute(
            """
            UPDATE tasks
            SET status=?, summary_json=?, error=?, finished_at=?
            WHERE task_id=?
            """,
            (status, _json_dumps(summary), str(error or "")[:4000], now, task_id),
        )
        conn.execute(
            """
            INSERT INTO task_events (task_id, event_type, message, data_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                task_id,
                event_type,
                message,
                _json_dumps(summary),
                now,
            ),
        )


def record_task_event(
    db_path: Path,
    task_id: int,
    event_type: str,
    message: str = "",
    data: dict[str, Any] | None = None,
) -> None:
    init_task_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO task_events (task_id, event_type, message, data_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, event_type, str(message or "")[:2000], _json_dumps(data), _now()),
        )


def get_running_task(db_path: Path) -> dict[str, Any] | None:
    init_task_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tasks WHERE status IN ('pending', 'running', 'cancel_requested') ORDER BY task_id DESC LIMIT 1"
        ).fetchone()
    return _task_from_row(row) if row else None


def get_latest_finished_task(db_path: Path) -> dict[str, Any] | None:
    init_task_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tasks WHERE status NOT IN ('pending', 'running') ORDER BY finished_at DESC, task_id DESC LIMIT 1"
        ).fetchone()
    return _task_from_row(row) if row else None


def list_tasks(
    db_path: Path,
    *,
    status: str = "",
    task_name: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    init_task_db(db_path)
    sql = "SELECT * FROM tasks WHERE 1=1"
    params: list[Any] = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if task_name:
        sql += " AND task_name=?"
        params.append(task_name)
    sql += " ORDER BY task_id DESC LIMIT ? OFFSET ?"
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    return [_task_from_row(row) for row in rows]


def count_tasks(db_path: Path, *, status: str = "", task_name: str = "") -> int:
    init_task_db(db_path)
    sql = "SELECT COUNT(*) FROM tasks WHERE 1=1"
    params: list[Any] = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if task_name:
        sql += " AND task_name=?"
        params.append(task_name)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def get_task(db_path: Path, task_id: int) -> dict[str, Any] | None:
    init_task_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    return _task_from_row(row) if row else None


def request_cancel(db_path: Path, task_id: int) -> dict[str, Any] | None:
    init_task_db(db_path)
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            return None
        task = _task_from_row(row)
        if task["status"] in ("pending", "running"):
            conn.execute(
                "UPDATE tasks SET status='cancel_requested' WHERE task_id=?",
                (task_id,),
            )
            conn.execute(
                """
                INSERT INTO task_events (task_id, event_type, message, created_at)
                VALUES (?, 'cancel_requested', 'Task cancellation requested', ?)
                """,
                (task_id, now),
            )
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            return _task_from_row(row)
        return task


def force_fail_task(db_path: Path, task_id: int, error: str = "Task force-failed by admin") -> dict[str, Any] | None:
    init_task_db(db_path)
    now = _now()
    message = str(error or "Task force-failed by admin")[:4000]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE tasks
            SET status='failed', error=?, finished_at=?
            WHERE task_id=?
            """,
            (message, now, task_id),
        )
        conn.execute(
            """
            INSERT INTO task_events (task_id, event_type, message, data_json, created_at)
            VALUES (?, 'force_failed', ?, ?, ?)
            """,
            (task_id, message, _json_dumps({"forced": True}), now),
        )
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    return _task_from_row(row)


def is_cancel_requested(db_path: Path, task_id: int) -> bool:
    init_task_db(db_path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    return bool(row and str(row[0]) == "cancel_requested")


def list_task_events(db_path: Path, task_id: int) -> list[dict[str, Any]]:
    init_task_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT event_id, task_id, event_type, message, data_json, created_at FROM task_events WHERE task_id=? ORDER BY event_id ASC",
            (task_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["data"] = _json_loads(item.pop("data_json", "{}"))
        out.append(item)
    return out


def recover_interrupted_tasks(db_path: Path) -> int:
    init_task_db(db_path)
    now = _now()
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT task_id FROM tasks WHERE status IN ('pending', 'running')").fetchall()
        task_ids = [int(row[0]) for row in rows]
        for task_id in task_ids:
            conn.execute(
                """
                UPDATE tasks
                SET status='failed', error='Task interrupted by service restart', finished_at=?
                WHERE task_id=?
                """,
                (now, task_id),
            )
            conn.execute(
                """
                INSERT INTO task_events (task_id, event_type, message, created_at)
                VALUES (?, 'failed', 'Task interrupted by service restart', ?)
                """,
                (task_id, now),
            )
    return len(task_ids)
