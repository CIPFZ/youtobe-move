from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.discovery.models import VideoCandidate


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _existing_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS videos (
                video_id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                channel_title TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '',
                duration_sec INTEGER NOT NULL DEFAULT 0,
                view_count INTEGER NOT NULL DEFAULT 0,
                keyword TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '',
                score REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                file_dir TEXT NOT NULL DEFAULT '',
                file_size INTEGER NOT NULL DEFAULT 0,
                thumbnail_path TEXT NOT NULL DEFAULT '',
                meta_path TEXT NOT NULL DEFAULT '',
                discovered_at TEXT NOT NULL,
                downloaded_at TEXT NOT NULL DEFAULT '',
                pulled_at TEXT NOT NULL DEFAULT '',
                expired_at TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                task_id INTEGER,
                download_progress REAL NOT NULL DEFAULT 0,
                download_attempts INTEGER NOT NULL DEFAULT 0,
                last_error_at TEXT NOT NULL DEFAULT '',
                raw_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        _add_column_if_missing(conn, 'videos', 'task_id', 'INTEGER')
        _add_column_if_missing(conn, 'videos', 'download_progress', 'REAL NOT NULL DEFAULT 0')
        _add_column_if_missing(conn, 'videos', 'download_attempts', 'INTEGER NOT NULL DEFAULT 0')
        _add_column_if_missing(conn, 'videos', 'last_error_at', "TEXT NOT NULL DEFAULT ''")
        conn.execute('CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_videos_category ON videos(category)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_videos_score ON videos(score DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_videos_discovered_at ON videos(discovered_at DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_videos_task_id ON videos(task_id)')
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS video_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                task_id INTEGER,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL DEFAULT '',
                data_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_video_events_video_id ON video_events(video_id, created_at DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_video_events_task_id ON video_events(task_id, created_at DESC)')


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _json_loads(value: str) -> Any:
    import json

    try:
        return json.loads(value or '{}')
    except json.JSONDecodeError:
        return {}


def add_video_event(
    db_path: Path,
    video_id: str,
    event_type: str,
    message: str = '',
    data: dict[str, Any] | None = None,
    task_id: int | None = None,
) -> None:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO video_events (video_id, task_id, event_type, message, data_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (video_id, task_id, event_type, str(message or '')[:2000], _json_dumps(data), _now()),
        )


def list_video_events(db_path: Path, video_id: str, limit: int = 100) -> list[dict[str, Any]]:
    init_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT event_id, video_id, task_id, event_type, message, data_json, created_at
            FROM video_events
            WHERE video_id=?
            ORDER BY event_id ASC
            LIMIT ?
            """,
            (video_id, max(1, min(int(limit), 500))),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item['data'] = _json_loads(item.pop('data_json', '{}'))
        out.append(item)
    return out


def upsert_candidates(db_path: Path, items: list[VideoCandidate]) -> int:
    if not items:
        return 0
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO videos (
                video_id, url, title, channel_title, published_at, duration_sec,
                view_count, keyword, category, score, status, discovered_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                url=excluded.url,
                title=excluded.title,
                channel_title=excluded.channel_title,
                published_at=excluded.published_at,
                duration_sec=excluded.duration_sec,
                view_count=excluded.view_count,
                keyword=excluded.keyword,
                category=excluded.category,
                score=excluded.score,
                discovered_at=excluded.discovered_at,
                raw_json=excluded.raw_json
            """,
            [
                (
                    x.video_id,
                    x.url,
                    x.title,
                    x.channel_title,
                    x.published_at,
                    x.duration_sec,
                    x.view_count,
                    x.keyword,
                    x.category or '',
                    x.score,
                    now,
                    x.raw_json,
                )
                for x in items
            ],
        )
    return len(items)


def get_pending_downloads(db_path: Path, limit: int = 10, min_score: float = 0.0) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT video_id, url, title, category, score
            FROM videos
            WHERE status = 'pending' AND score >= ?
            ORDER BY score DESC
            LIMIT ?
            """,
            (min_score, max(1, min(limit, 100))),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_downloading(db_path: Path, video_id: str, task_id: int | None = None) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE videos
            SET status='downloading', task_id=COALESCE(?, task_id),
                download_progress=0, download_attempts=download_attempts + 1
            WHERE video_id=?
            """,
            (task_id, video_id),
        )
    add_video_event(db_path, video_id, 'downloading', 'Download started', task_id=task_id)


def update_download_progress(
    db_path: Path,
    video_id: str,
    progress: float,
    *,
    task_id: int | None = None,
    message: str = '',
) -> None:
    bounded = max(0.0, min(float(progress), 100.0))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE videos
            SET download_progress=?, task_id=COALESCE(?, task_id)
            WHERE video_id=?
            """,
            (bounded, task_id, video_id),
        )
    add_video_event(
        db_path,
        video_id,
        'progress',
        message or f'Download progress {bounded:.1f}%',
        {'progress': bounded},
        task_id=task_id,
    )


def ensure_video_row(db_path: Path, video_id: str, url: str, category: str) -> None:
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO videos (
                video_id, url, category, keyword, score, status, discovered_at, raw_json
            ) VALUES (?, ?, ?, 'manual', 0.0, 'pending', ?, '{}')
            """,
            (video_id, url, category or 'manual', now),
        )


def mark_downloaded(
    db_path: Path,
    video_id: str,
    file_dir: str,
    file_size: int,
    thumbnail_path: str = '',
    meta_path: str = '',
    task_id: int | None = None,
) -> None:
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE videos
            SET status='downloaded', file_dir=?, file_size=?, thumbnail_path=?,
                meta_path=?, downloaded_at=?, error='', task_id=COALESCE(?, task_id),
                download_progress=100
            WHERE video_id=?
            """,
            (file_dir, file_size, thumbnail_path, meta_path, now, task_id, video_id),
        )
    add_video_event(db_path, video_id, 'downloaded', 'Download finished', {'file_size': file_size}, task_id=task_id)


def mark_download_failed(db_path: Path, video_id: str, error: str, task_id: int | None = None) -> None:
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE videos
            SET status='failed', error=?, task_id=COALESCE(?, task_id),
                last_error_at=?, download_progress=0
            WHERE video_id=?
            """,
            (str(error)[:2000], task_id, now, video_id),
        )
    add_video_event(db_path, video_id, 'failed', str(error)[:2000], {'error': str(error)}, task_id=task_id)


def mark_pulled(db_path: Path, video_id: str, task_id: int | None = None) -> None:
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE videos SET status='pulled', file_dir='', file_size=0, pulled_at=? WHERE video_id=?",
            (now, video_id),
        )
    add_video_event(db_path, video_id, 'pulled', 'Video pulled by local server', task_id=task_id)


def mark_expired(db_path: Path, video_id: str, task_id: int | None = None) -> None:
    now = _now()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE videos SET status='expired', file_dir='', file_size=0, expired_at=? WHERE video_id=?",
            (now, video_id),
        )
    add_video_event(db_path, video_id, 'expired', 'Video files expired or were force deleted', task_id=task_id)


def get_downloaded_oldest(db_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT video_id, file_dir AS file_path, file_size, downloaded_at
            FROM videos
            WHERE status = 'downloaded'
            ORDER BY downloaded_at ASC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_expired_downloads(db_path: Path, max_days: int, limit: int = 50) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT video_id, file_dir AS file_path, file_size, downloaded_at
            FROM videos
            WHERE status = 'downloaded'
              AND downloaded_at != ''
              AND datetime(downloaded_at) < datetime('now', ?)
            ORDER BY downloaded_at ASC
            LIMIT ?
            """,
            (f'-{max(int(max_days), 1)} days', max(1, min(limit, 500))),
        ).fetchall()
    return [dict(r) for r in rows]


def get_total_storage_bytes(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM videos WHERE status = 'downloaded'"
        ).fetchone()
    return int(row[0]) if row else 0


def _video_select_sql() -> str:
    return """
    SELECT video_id, url, title, channel_title, published_at, duration_sec,
           view_count, keyword, category, score, status, status AS download_status,
           file_dir, file_dir AS file_path, file_size, thumbnail_path, meta_path,
           task_id, download_progress, download_attempts, last_error_at,
           downloaded_at, pulled_at, expired_at, error, error AS download_error,
           discovered_at, raw_json
    FROM videos
    """


def list_videos(
    db_path: Path,
    *,
    category: str = '',
    download_status: str = '',
    min_score: float = 0.0,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = _video_select_sql() + " WHERE 1=1"
    params: list[Any] = []
    if category:
        sql += ' AND category = ?'
        params.append(category)
    if download_status:
        sql += ' AND status = ?'
        params.append(download_status)
    if min_score > 0:
        sql += ' AND score >= ?'
        params.append(min_score)
    sql += ' ORDER BY score DESC, discovered_at DESC LIMIT ? OFFSET ?'
    params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def count_videos(db_path: Path, *, category: str = '', download_status: str = '', min_score: float = 0.0) -> int:
    sql = 'SELECT COUNT(*) FROM videos WHERE 1=1'
    params: list[Any] = []
    if category:
        sql += ' AND category = ?'
        params.append(category)
    if download_status:
        sql += ' AND status = ?'
        params.append(download_status)
    if min_score > 0:
        sql += ' AND score >= ?'
        params.append(min_score)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def get_video_by_id(db_path: Path, video_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            _video_select_sql() + " WHERE video_id=?",
            (video_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_storage_stats(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        total_size = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM videos WHERE status = 'downloaded'"
        ).fetchone()[0]
        by_cat_rows = conn.execute(
            "SELECT category, COUNT(*) FROM videos GROUP BY category"
        ).fetchall()
        by_status_rows = conn.execute(
            "SELECT status, COUNT(*) FROM videos GROUP BY status"
        ).fetchall()
    return {
        'total_videos': total,
        'total_size_gb': round(int(total_size) / (1024 ** 3), 2),
        'by_category': {str(r[0]) or 'uncategorised': r[1] for r in by_cat_rows},
        'by_status': {str(r[0]): r[1] for r in by_status_rows},
    }
