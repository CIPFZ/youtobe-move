"""HK server puller: sync videos from youtobe-parser API to local storage."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from conf import (BASE_DIR, HK_SERVER_URL, HK_API_TOKEN, HK_POLL_INTERVAL_MINUTES,
                      HK_AUTO_DOWNLOAD, HK_DOWNLOAD_DIRNAME)
except ImportError:
    raise RuntimeError("conf.py not found. Copy conf.example.py to conf.py and configure it.")

logger = logging.getLogger("hk_puller")
_sync_lock = threading.Lock()

# ── DB helpers ──

def _db_path() -> Path:
    return Path(BASE_DIR) / "db" / "database.db"


def _get_conn() -> sqlite3.Connection:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _download_dir() -> Path:
    return Path(BASE_DIR) / "videoFile" / HK_DOWNLOAD_DIRNAME


def _auth_headers() -> dict[str, str]:
    h: dict[str, str] = {"User-Agent": "social-auto-upload/1.0"}
    token = (HK_API_TOKEN or "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ── HK API calls ──

def fetch_hk_videos(
    status: str = "downloaded",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch video list from HK API. Returns list of video dicts."""
    url = f"{HK_SERVER_URL.rstrip('/')}/api/videos"
    params: dict[str, Any] = {"download_status": status, "limit": limit, "offset": offset}
    resp = requests.get(url, params=params, headers=_auth_headers(), timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return list(data.get("videos", []))


def fetch_hk_stats() -> dict[str, Any]:
    """Fetch storage stats from HK API."""
    url = f"{HK_SERVER_URL.rstrip('/')}/api/stats"
    resp = requests.get(url, headers=_auth_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def download_hk_file(video_id: str, file_type: str, dest_path: Path) -> bool:
    """Download a single file (video/audio/thumbnail) from HK API.
    Returns True on success.
    """
    url = f"{HK_SERVER_URL.rstrip('/')}/api/videos/{video_id}/file"
    params = {"type": file_type}
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, params=params, headers=_auth_headers(),
                          stream=True, timeout=(30, 300)) as resp:
            resp.raise_for_status()
            with dest_path.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception:
        # clean up partial file
        if dest_path.exists():
            try:
                dest_path.unlink()
            except OSError:
                pass
        raise


# ── local DB operations ──

def _local_video_exists(conn: sqlite3.Connection, video_id: str) -> bool:
    row = conn.execute(
        "SELECT download_status FROM hk_videos WHERE video_id=?",
        (video_id,),
    ).fetchone()
    if row is None:
        return False
    return row[0] == "downloaded"


def _upsert_hk_video(conn: sqlite3.Connection, v: dict[str, Any]) -> None:
    """Insert a new video record from HK API response into local DB (status=pending)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO hk_videos (
            video_id, title, url, category, view_count, score,
            hk_downloaded_at, synced_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            str(v.get("video_id", "")),
            str(v.get("title", "")),
            str(v.get("url", "")),
            str(v.get("category", "")),
            int(v.get("view_count", 0) or 0),
            float(v.get("score", 0.0) or 0.0),
            str(v.get("downloaded_at", "")),
        ),
    )


def _mark_downloading(conn: sqlite3.Connection, video_id: str) -> None:
    conn.execute(
        "UPDATE hk_videos SET download_status='downloading' WHERE video_id=?",
        (video_id,),
    )
    conn.commit()


def _mark_downloaded(conn: sqlite3.Connection, video_id: str, file_path: str,
                     file_size: int, thumbnail_path: str = "") -> None:
    conn.execute(
        """
        UPDATE hk_videos SET download_status='downloaded', file_path=?, file_size=?,
        thumbnail_path=?, local_downloaded_at=datetime('now')
        WHERE video_id=?
        """,
        (file_path, file_size, thumbnail_path, video_id),
    )
    conn.commit()


def _mark_failed(conn: sqlite3.Connection, video_id: str, error: str) -> None:
    conn.execute(
        "UPDATE hk_videos SET download_status='failed', error=? WHERE video_id=?",
        (str(error)[:2000], video_id),
    )
    conn.commit()


def _get_pending(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT video_id, title, url, category, score
        FROM hk_videos WHERE download_status='pending'
        ORDER BY score DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {"video_id": r[0], "title": r[1], "url": r[2], "category": r[3], "score": r[4]}
        for r in rows
    ]


def _record_sync_log(conn: sqlite3.Connection, new_count: int, downloaded: int, error: str = "") -> None:
    conn.execute(
        "INSERT INTO hk_sync_log (new_count, downloaded_count, error) VALUES (?, ?, ?)",
        (new_count, downloaded, error),
    )
    conn.commit()


# ── upload status ──

def mark_uploaded(video_id: str, platform: str = "", account: str = "") -> bool:
    """Mark a video as uploaded to a platform. Returns True on success."""
    try:
        conn = _get_conn()
        conn.execute(
            """
            UPDATE hk_videos SET upload_status='uploaded', uploaded_at=datetime('now'),
            upload_platform=?, upload_account=?
            WHERE video_id=?
            """,
            (platform, account, video_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as exc:
        logger.error("mark_uploaded failed: %s", exc)
        return False


def list_pending_uploads(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """Get downloaded-but-not-yet-uploaded videos."""
    conn = _get_conn()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM hk_videos
        WHERE download_status='downloaded' AND upload_status='pending'
        ORDER BY score DESC LIMIT ? OFFSET ?
        """,
        (max(1, min(limit, 200)), max(0, offset)),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── main pipeline ──

def sync_hk_videos() -> dict[str, Any]:
    """Run one full sync cycle: fetch list → dedupe → download → log.

    Thread-safe: only one sync runs at a time.
    """
    if not _sync_lock.acquire(blocking=False):
        logger.info("Sync already in progress, skipping")
        return {"skipped": True, "reason": "already running"}

    summary: dict[str, Any] = {"new": 0, "downloaded": 0, "failed": 0, "error": ""}
    try:
        logger.info("=== HK sync cycle start ===")
        conn = _get_conn()

        # 1. Fetch video list from HK
        all_videos: list[dict[str, Any]] = []
        offset = 0
        while True:
            batch = fetch_hk_videos(status="downloaded", limit=50, offset=offset)
            if not batch:
                break
            all_videos.extend(batch)
            if len(batch) < 50:
                break
            offset += 50

        logger.info("Fetched %d videos from HK API", len(all_videos))

        # 2. Deduplicate & insert new
        new_ids: list[str] = []
        for v in all_videos:
            vid = str(v.get("video_id", ""))
            if not vid:
                continue
            if _local_video_exists(conn, vid):
                continue
            _upsert_hk_video(conn, v)
            new_ids.append(vid)
        conn.commit()
        summary["new"] = len(new_ids)
        logger.info("New videos to download: %d", len(new_ids))

        # 3. Download pending videos
        if HK_AUTO_DOWNLOAD and new_ids:
            media_root = _download_dir()
            for vid in new_ids:
                # re-fetch from DB to get category
                row = conn.execute(
                    "SELECT video_id, category FROM hk_videos WHERE video_id=?",
                    (vid,),
                ).fetchone()
                if not row:
                    continue
                category = (row[1] or "uncategorised").strip()
                out_dir = media_root / category / vid
                out_dir.mkdir(parents=True, exist_ok=True)

                logger.info("Downloading video %s (category=%s) → %s", vid, category, out_dir)
                _mark_downloading(conn, vid)

                video_file = out_dir / f"{vid}.mp4"
                thumbnail_file = out_dir / f"{vid}.jpg"
                ok = True
                try:
                    download_hk_file(vid, "video", video_file)
                    try:
                        download_hk_file(vid, "thumbnail", thumbnail_file)
                    except Exception:
                        # thumbnail is optional
                        thumbnail_file = Path("")
                    file_size = video_file.stat().st_size if video_file.exists() else 0
                    _mark_downloaded(conn, vid, str(out_dir), file_size, str(thumbnail_file))
                    summary["downloaded"] += 1
                    logger.info("Download OK: %s size=%d", vid, file_size)
                except Exception as exc:
                    _mark_failed(conn, vid, str(exc))
                    summary["failed"] += 1
                    logger.warning("Download failed: %s err=%s", vid, exc)

        _record_sync_log(conn, summary["new"], summary["downloaded"])
    except Exception as exc:
        logger.error("Sync cycle failed: %s", exc, exc_info=True)
        summary["error"] = str(exc)
    finally:
        _sync_lock.release()

    logger.info(
        "=== HK sync cycle done: new=%d downloaded=%d failed=%d ===",
        summary["new"], summary["downloaded"], summary["failed"],
    )
    return summary


# ── background poller ──

def run_hk_poller() -> threading.Thread:
    """Start a background daemon thread that polls HK server periodically."""
    interval_sec = max(30, int(HK_POLL_INTERVAL_MINUTES) * 60)

    def _loop() -> None:
        # initial delay to let Flask settle
        time.sleep(5)
        while True:
            try:
                sync_hk_videos()
            except Exception as exc:
                logger.error("Poller error: %s", exc)
            time.sleep(interval_sec)

    t = threading.Thread(target=_loop, daemon=True, name="hk-poller")
    t.start()
    logger.info("HK poller started (interval=%d min)", HK_POLL_INTERVAL_MINUTES)
    return t
