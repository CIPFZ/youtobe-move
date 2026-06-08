from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.discovery.models import VideoCandidate


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names currently present in *table*."""
    rows = conn.execute(f'PRAGMA table_info({table})').fetchall()
    return {str(r[1]) for r in rows}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, col_name: str, col_def: str) -> None:
    """Idempotently add a column to *table* if it does not already exist."""
    cols = _existing_columns(conn, table)
    if col_name not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col_name} {col_def}')


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply schema additions for the download/classification pipeline."""
    _add_column_if_missing(conn, 'discovered_videos', 'category', "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, 'discovered_videos', 'download_status', "TEXT NOT NULL DEFAULT 'pending'")
    _add_column_if_missing(conn, 'discovered_videos', 'file_path', "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, 'discovered_videos', 'file_size', 'INTEGER NOT NULL DEFAULT 0')
    _add_column_if_missing(conn, 'discovered_videos', 'downloaded_at', "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, 'discovered_videos', 'download_error', "TEXT NOT NULL DEFAULT ''")
    # process pipeline
    _add_column_if_missing(conn, 'discovered_videos', 'process_status', "TEXT NOT NULL DEFAULT 'pending'")
    _add_column_if_missing(conn, 'discovered_videos', 'process_retries', 'INTEGER NOT NULL DEFAULT 0')
    _add_column_if_missing(conn, 'discovered_videos', 'process_error', "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, 'discovered_videos', 'bilingual_video', "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, 'discovered_videos', 'dubbed_video', "TEXT NOT NULL DEFAULT ''")
    # indices
    conn.execute('CREATE INDEX IF NOT EXISTS idx_discovered_download_status ON discovered_videos(download_status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_discovered_category ON discovered_videos(category)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_discovered_process_status ON discovered_videos(process_status)')


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        # enable WAL for better concurrent read/write
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discovered_videos (
                video_id TEXT PRIMARY KEY,
                discovered_at TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                channel_title TEXT NOT NULL,
                published_at TEXT NOT NULL,
                language_hint TEXT NOT NULL,
                duration_sec INTEGER NOT NULL,
                view_count INTEGER NOT NULL,
                comment_count INTEGER NOT NULL,
                like_count INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                score REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'discovered',
                raw_json TEXT NOT NULL
            )
            """
        )
        # idempotent migration for new columns
        _migrate_schema(conn)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_discovered_score ON discovered_videos(score DESC)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_discovered_at ON discovered_videos(discovered_at DESC)')
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT '',
                finished_at TEXT NOT NULL DEFAULT '',
                error TEXT NOT NULL DEFAULT '',
                bilingual_video TEXT NOT NULL DEFAULT '',
                dubbed_video TEXT NOT NULL DEFAULT '',
                log_path TEXT NOT NULL DEFAULT ''
            )
            """
        )
        conn.execute('CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON processing_jobs(status, created_at DESC)')


def upsert_candidates(db_path: Path, items: list[VideoCandidate]) -> int:
    if not items:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO discovered_videos (
                video_id, discovered_at, url, title, description, channel_id, channel_title,
                published_at, language_hint, duration_sec, view_count, comment_count, like_count,
                keyword, category, score, status, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', ?)
            ON CONFLICT(video_id) DO UPDATE SET
                discovered_at=excluded.discovered_at,
                url=excluded.url,
                title=excluded.title,
                description=excluded.description,
                channel_id=excluded.channel_id,
                channel_title=excluded.channel_title,
                published_at=excluded.published_at,
                language_hint=excluded.language_hint,
                duration_sec=excluded.duration_sec,
                view_count=excluded.view_count,
                comment_count=excluded.comment_count,
                like_count=excluded.like_count,
                keyword=excluded.keyword,
                category=excluded.category,
                score=excluded.score,
                raw_json=excluded.raw_json
            """,
            [
                (
                    x.video_id,
                    now,
                    x.url,
                    x.title,
                    x.description,
                    x.channel_id,
                    x.channel_title,
                    x.published_at,
                    x.language_hint,
                    x.duration_sec,
                    x.view_count,
                    x.comment_count,
                    x.like_count,
                    x.keyword,
                    x.category,
                    x.score,
                    x.raw_json,
                )
                for x in items
            ],
        )
    return len(items)


# ── download status management ──

def get_pending_downloads(db_path: Path, limit: int = 10, min_score: float = 0.0) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT video_id, url, title, category, score
            FROM discovered_videos
            WHERE download_status = 'pending' AND score >= ?
            ORDER BY score DESC
            LIMIT ?
            """,
            (min_score, max(1, min(limit, 100))),
        ).fetchall()
    return [{'video_id': r[0], 'url': r[1], 'title': r[2], 'category': r[3], 'score': r[4]} for r in rows]


def mark_downloading(db_path: Path, video_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET download_status='downloading' WHERE video_id=?",
            (video_id,),
        )


def mark_downloaded(db_path: Path, video_id: str, file_path: str, file_size: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET download_status='downloaded', file_path=?, file_size=?, downloaded_at=? WHERE video_id=?",
            (file_path, file_size, now, video_id),
        )


def mark_download_failed(db_path: Path, video_id: str, error: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET download_status='failed', download_error=?, downloaded_at=? WHERE video_id=?",
            (str(error)[:2000], now, video_id),
        )


def mark_cleaned(db_path: Path, video_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET download_status='cleaned', file_path='', file_size=0 WHERE video_id=?",
            (video_id,),
        )


# ── disk cleanup helpers ──

def get_downloaded_oldest(db_path: Path, limit: int = 50) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT video_id, file_path, file_size, downloaded_at
            FROM discovered_videos
            WHERE download_status = 'downloaded'
            ORDER BY downloaded_at ASC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [{'video_id': r[0], 'file_path': r[1], 'file_size': r[2], 'downloaded_at': r[3]} for r in rows]


def get_expired_downloads(db_path: Path, max_days: int, limit: int = 50) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT video_id, file_path, file_size, downloaded_at
            FROM discovered_videos
            WHERE download_status = 'downloaded'
              AND downloaded_at != ''
              AND datetime(downloaded_at) < datetime('now', ?)
            ORDER BY downloaded_at ASC
            LIMIT ?
            """,
            (f'-{max(int(max_days), 1)} days', max(1, min(limit, 500))),
        ).fetchall()
    return [{'video_id': r[0], 'file_path': r[1], 'file_size': r[2], 'downloaded_at': r[3]} for r in rows]


def get_total_storage_bytes(db_path: Path) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM discovered_videos WHERE download_status = 'downloaded'"
        ).fetchone()
    return int(row[0]) if row else 0


# ── process pipeline ──

def get_pending_processes(db_path: Path, max_retries: int = 3, limit: int = 5) -> list[dict[str, Any]]:
    """Return download_status='downloaded' videos that need processing.

    Includes: process_status='pending' OR (process_status='failed' AND process_retries < max_retries).
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT video_id, file_path, title, category, score
            FROM discovered_videos
            WHERE download_status = 'downloaded'
              AND (
                  process_status = 'pending'
                  OR (process_status = 'failed' AND process_retries < ?)
              )
            ORDER BY score DESC
            LIMIT ?
            """,
            (max(0, int(max_retries)), max(1, min(int(limit), 20))),
        ).fetchall()
    return [{'video_id': r[0], 'file_path': r[1], 'title': r[2], 'category': r[3], 'score': r[4]} for r in rows]


def mark_processing(db_path: Path, video_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET process_status='processing' WHERE video_id=?",
            (video_id,),
        )


def mark_processed(db_path: Path, video_id: str, bilingual_video: str = '', dubbed_video: str = '') -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET process_status='processed', bilingual_video=?, dubbed_video=?, process_error='' WHERE video_id=?",
            (bilingual_video, dubbed_video, video_id),
        )


def mark_process_failed(db_path: Path, video_id: str, error: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET process_status='failed', process_error=?, process_retries = process_retries + 1 WHERE video_id=?",
            (str(error)[:5000], video_id),
        )


def reset_process_status(db_path: Path, video_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE discovered_videos SET process_status='pending', process_retries=0, process_error='' WHERE video_id=?",
            (video_id,),
        )


# ── query API ──

def list_videos(
    db_path: Path,
    *,
    category: str = '',
    download_status: str = '',
    min_score: float = 0.0,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    sql = """
    SELECT video_id, url, title, description, channel_id, channel_title, published_at,
           language_hint, duration_sec, view_count, comment_count, like_count,
           keyword, category, score, download_status, file_path, file_size,
           downloaded_at, download_error, discovered_at
    FROM discovered_videos WHERE 1=1
    """
    params: list[Any] = []
    if category:
        sql += ' AND category = ?'
        params.append(category)
    if download_status:
        sql += ' AND download_status = ?'
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
    sql = 'SELECT COUNT(*) FROM discovered_videos WHERE 1=1'
    params: list[Any] = []
    if category:
        sql += ' AND category = ?'
        params.append(category)
    if download_status:
        sql += ' AND download_status = ?'
        params.append(download_status)
    if min_score > 0:
        sql += ' AND score >= ?'
        params.append(min_score)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def get_video_by_id(db_path: Path, video_id: str) -> dict[str, Any] | None:
    cols = [
        'video_id', 'url', 'title', 'description', 'channel_id', 'channel_title',
        'published_at', 'language_hint', 'duration_sec', 'view_count', 'comment_count',
        'like_count', 'keyword', 'category', 'score', 'download_status', 'file_path',
        'file_size', 'downloaded_at', 'download_error', 'discovered_at',
    ]
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            f"SELECT {', '.join(cols)} FROM discovered_videos WHERE video_id=?",
            (video_id,),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_storage_stats(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM discovered_videos").fetchone()[0]
        total_size = conn.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM discovered_videos WHERE download_status = 'downloaded'"
        ).fetchone()[0]
        by_cat_rows = conn.execute(
            "SELECT category, COUNT(*) FROM discovered_videos GROUP BY category"
        ).fetchall()
        by_status_rows = conn.execute(
            "SELECT download_status, COUNT(*) FROM discovered_videos GROUP BY download_status"
        ).fetchall()
    return {
        'total_videos': total,
        'total_size_gb': round(int(total_size) / (1024 ** 3), 2),
        'by_category': {str(r[0]) or 'uncategorised': r[1] for r in by_cat_rows},
        'by_status': {str(r[0]): r[1] for r in by_status_rows},
    }


# ── processing jobs (kept for backward compat) ──

def enqueue_processing_job(db_path: Path, video_id: str) -> tuple[bool, str]:
    vid = video_id.strip()
    if not vid:
        return False, 'video_id is empty'
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT video_id, url FROM discovered_videos WHERE video_id=?',
            (vid,),
        ).fetchone()
        if not row:
            return False, f'video_id not found: {vid}'
        exists = conn.execute(
            "SELECT id FROM processing_jobs WHERE video_id=? AND status IN ('pending','running') ORDER BY id DESC LIMIT 1",
            (vid,),
        ).fetchone()
        if exists:
            return False, f'job already queued/running for {vid}'
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            'INSERT INTO processing_jobs(video_id, url, status, created_at) VALUES (?, ?, ?, ?)',
            (row[0], row[1], 'pending', now),
        )
    return True, f'job queued for {vid}'


def claim_next_job(db_path: Path) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as conn:
        conn.isolation_level = None
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute(
            "SELECT id, video_id, url FROM processing_jobs WHERE status='pending' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            conn.execute('COMMIT')
            return None
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE processing_jobs SET status='running', started_at=? WHERE id=?",
            (now, int(row[0])),
        )
        conn.execute('COMMIT')
    return {'id': int(row[0]), 'video_id': str(row[1]), 'url': str(row[2])}


def complete_job(
    db_path: Path,
    *,
    job_id: int,
    success: bool,
    error: str = '',
    bilingual_video: str = '',
    dubbed_video: str = '',
    log_path: str = '',
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    status = 'success' if success else 'failed'
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE processing_jobs
            SET status=?, finished_at=?, error=?, bilingual_video=?, dubbed_video=?, log_path=?
            WHERE id=?
            """,
            (status, now, error, bilingual_video, dubbed_video, log_path, int(job_id)),
        )


def list_jobs(db_path: Path, limit: int = 30) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            SELECT id, video_id, status, created_at, started_at, finished_at, error, bilingual_video, dubbed_video
            FROM processing_jobs
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit), 300)),),
        )
        return list(cur.fetchall())
