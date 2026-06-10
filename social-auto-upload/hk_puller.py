"""HK server puller: sync videos from hk-server API → local merge → Bilibili publish."""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from conf import (
        BASE_DIR, HK_SERVER_URL, HK_API_TOKEN, HK_POLL_INTERVAL_MINUTES,
        HK_AUTO_DOWNLOAD, HK_DOWNLOAD_DIRNAME, HK_DOWNLOAD_INTERVAL_SEC,
    )
except ImportError:
    raise RuntimeError("conf.py not found. Copy conf.example.py to conf.py and configure it.")

# ── Bilibili category mapping (YouTube category → Bilibili tid) ──
BILIBILI_TID_MAP = {
    "pets": 217,    # 动物圈
    "beauty": 163,  # 时尚
    "funny": 138,   # 搞笑
    "": 174,        # 生活 (default)
}

# ── Tag mapping ──
BILIBILI_TAG_MAP = {
    "pets": ["宠物", "萌宠", "动物"],
    "beauty": ["美妆", "时尚", "穿搭"],
    "funny": ["搞笑", "幽默", "沙雕"],
}

logger = logging.getLogger("hk_puller")
_sync_lock = threading.Lock()

# HK server session — bypass local proxy (direct connect)
_hk_session = requests.Session()
_hk_session.proxies = {"http": None, "https": None}
_hk_session.trust_env = False


# ── DB helpers ──

def _db_path() -> Path:
    return Path(BASE_DIR) / "db" / "database.db"


def _get_conn() -> sqlite3.Connection:
    db = _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    # add missing columns (idempotent)
    for col, defn in [
        ("thumbnail_path", "TEXT NOT NULL DEFAULT ''"),
        ("meta_path", "TEXT NOT NULL DEFAULT ''"),
    ]:
        try:
            conn.execute(f"ALTER TABLE hk_videos ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError:
            pass  # column already exists
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

def fetch_hk_videos(status: str = "downloaded", limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    url = f"{HK_SERVER_URL.rstrip('/')}/api/videos"
    params: dict[str, Any] = {"download_status": status, "limit": limit, "offset": offset}
    resp = _hk_session.get(url, params=params, headers=_auth_headers(), timeout=30)
    resp.raise_for_status()
    return list(resp.json().get("videos", []))


def fetch_hk_stats() -> dict[str, Any]:
    url = f"{HK_SERVER_URL.rstrip('/')}/api/stats"
    resp = _hk_session.get(url, headers=_auth_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def download_hk_file(video_id: str, file_type: str, dest_path: Path, max_retries: int = 3) -> bool:
    """Download a single file from HK API with resume support and retry on connection errors."""
    url = f"{HK_SERVER_URL.rstrip('/')}/api/videos/{video_id}/file"
    params = {"type": file_type}
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, max_retries + 1):
        try:
            # resume from partial download if exists
            existing_size = dest_path.stat().st_size if dest_path.exists() else 0
            headers = dict(_auth_headers())
            if existing_size > 0:
                headers["Range"] = f"bytes={existing_size}-"

            with _hk_session.get(url, params=params, headers=headers,
                              stream=True, timeout=(30, 600)) as resp:
                if resp.status_code not in (200, 206):
                    resp.raise_for_status()

                mode = "ab" if resp.status_code == 206 else "wb"
                with dest_path.open(mode) as f:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            f.write(chunk)

            # verify download
            if dest_path.stat().st_size == 0:
                raise RuntimeError("Downloaded empty file")
            return True

        except Exception as exc:
            if attempt < max_retries:
                wait = attempt * 10
                logger.warning("Download %s/%s retry %d/%d after %ds: %s",
                               video_id, file_type, attempt, max_retries, wait, exc)
                time.sleep(wait)
            else:
                # clean up partial on final failure
                if dest_path.exists():
                    try:
                        dest_path.unlink()
                    except OSError:
                        pass
                raise


def download_hk_meta(video_id: str) -> dict[str, Any]:
    """Fetch full .video_info.json metadata from HK server."""
    url = f"{HK_SERVER_URL.rstrip('/')}/api/videos/{video_id}/meta"
    resp = _hk_session.get(url, headers=_auth_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def delete_hk_video(video_id: str) -> bool:
    """Notify HK server that video has been pulled (deletes server-side files)."""
    url = f"{HK_SERVER_URL.rstrip('/')}/api/videos/{video_id}"
    resp = _hk_session.delete(url, headers=_auth_headers(), timeout=30)
    return resp.status_code == 200


# ── ffmpeg merge (auto-detect AV1 → GPU transcode to H.264) ──

def _probe_vcodec(video_path: Path) -> str:
    """Return video codec name, e.g. 'h264' or 'av1'."""
    import subprocess as _sp
    r = _sp.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name", "-of", "default=noprint_wrappers=1:nokey=1",
         str(video_path)],
        capture_output=True, text=True, timeout=15,
    )
    return r.stdout.strip()


def merge_video_audio(video_path: Path, audio_path: Path, output_path: Path) -> Path:
    """Merge video + audio. If video codec is AV1, GPU-transcode to H.264."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vcodec = _probe_vcodec(video_path)

    if vcodec in ("av1", "vp9", "vp8"):
        logger.info("Video codec is %s, GPU-transcoding to H.264", vcodec)
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
            "-i", str(video_path), "-i", str(audio_path),
            "-c:v", "h264_nvenc", "-preset", "p6",
            "-rc", "vbr", "-cq", "23", "-b:v", "0",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path), "-i", str(audio_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg merge failed: {result.stderr.strip()}")
    return output_path


# ── Bilibili upload ──

def _load_bilibili_account() -> str:
    """Find first configured bilibili account, or use default."""
    from pathlib import Path as P
    cookies_dir = P(BASE_DIR) / "cookies"
    if not cookies_dir.exists():
        raise RuntimeError(f"Bilibili account not configured. Run: sau bilibili login --account <name>")
    candidates = sorted(cookies_dir.glob("bilibili_*.json"))
    if not candidates:
        raise RuntimeError(f"No bilibili cookie file found in {cookies_dir}")
    # extract account name from filename: bilibili_xxx.json → xxx
    name = candidates[0].stem.replace("bilibili_", "")
    logger.info("Using bilibili account: %s", name)
    return name


def upload_to_bilibili(
    video_path: Path,
    title: str,
    description: str,
    tid: int,
    tags: list[str],
    account: str | None = None,
    dtime: datetime | None = None,
) -> bool:
    """Upload a video to Bilibili via biliup CLI."""
    try:
        from uploader.bilibili_uploader.runtime import ensure_biliup_binary, run_biliup_command
    except ImportError:
        raise RuntimeError("Cannot import bilibili uploader. Run from social-auto-upload directory.")

    ensure_biliup_binary(force_check=False)
    account_name = account or _load_bilibili_account()
    account_file = Path(BASE_DIR) / "cookies" / f"bilibili_{account_name}.json"
    if not account_file.exists():
        raise RuntimeError(
            f"Bilibili account file missing: {account_file}. "
            f"Run: sau bilibili login --account {account_name}"
        )

    arguments = [
        "-u", str(account_file),
        "upload",
        str(video_path),
        "--title", title,
        "--desc", description,
        "--tid", str(tid),
    ]
    if tags:
        arguments.extend(["--tag", ",".join(tags)])
    if dtime:
        arguments.extend(["--dtime", str(int(dtime.timestamp()))])

    result = run_biliup_command(arguments)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip() or "Bilibili upload failed")
    return True


# ── local DB operations ──

def _local_video_exists(conn: sqlite3.Connection, video_id: str) -> bool:
    row = conn.execute("SELECT download_status FROM hk_videos WHERE video_id=?", (video_id,)).fetchone()
    if row is None:
        return False
    return row[0] == "downloaded"


def _upsert_hk_video(conn: sqlite3.Connection, v: dict[str, Any]) -> None:
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
    conn.execute("UPDATE hk_videos SET download_status='downloading' WHERE video_id=?", (video_id,))
    conn.commit()


def _mark_downloaded(conn: sqlite3.Connection, video_id: str, file_path: str,
                     file_size: int, thumbnail_path: str = "", meta_path: str = "") -> None:
    conn.execute(
        """
        UPDATE hk_videos SET download_status='downloaded', file_path=?, file_size=?,
        thumbnail_path=?, meta_path=?, local_downloaded_at=datetime('now')
        WHERE video_id=?
        """,
        (file_path, file_size, thumbnail_path, meta_path, video_id),
    )
    conn.commit()


def _mark_failed(conn: sqlite3.Connection, video_id: str, error: str) -> None:
    conn.execute(
        "UPDATE hk_videos SET download_status='failed', error=? WHERE video_id=?",
        (str(error)[:2000], video_id),
    )
    conn.commit()


def _mark_uploaded(conn: sqlite3.Connection, video_id: str, platform: str = "bilibili") -> None:
    conn.execute(
        "UPDATE hk_videos SET upload_status='uploaded', uploaded_at=datetime('now'), upload_platform=? WHERE video_id=?",
        (platform, video_id),
    )
    conn.commit()


def _mark_upload_failed(conn: sqlite3.Connection, video_id: str, error: str) -> None:
    conn.execute(
        "UPDATE hk_videos SET upload_status='failed', error=? WHERE video_id=?",
        (str(error)[:2000], video_id),
    )
    conn.commit()


def _record_sync_log(conn: sqlite3.Connection, new_count: int, downloaded: int, error: str = "") -> None:
    conn.execute(
        "INSERT INTO hk_sync_log (new_count, downloaded_count, error) VALUES (?, ?, ?)",
        (new_count, downloaded, error),
    )
    conn.commit()


# ── main pipeline ──

def sync_hk_videos() -> dict[str, Any]:
    """Run one full sync cycle: fetch → download video+audio+meta → merge → confirm delete."""
    if not _sync_lock.acquire(blocking=False):
        logger.info("Sync already in progress, skipping")
        return {"skipped": True, "reason": "already running"}

    summary: dict[str, Any] = {"new": 0, "downloaded": 0, "merged": 0, "deleted_hk": 0, "failed": 0, "error": ""}
    try:
        logger.info("=== HK sync cycle start ===")
        conn = _get_conn()

        # 0. Reset previously-failed downloads to pending (retry)
        conn.execute(
            "UPDATE hk_videos SET download_status='pending', error='' WHERE download_status='failed'"
        )
        conn.commit()

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

        # 3. Download + merge each new video
        if HK_AUTO_DOWNLOAD and new_ids:
            for vid in new_ids:
                row = conn.execute(
                    "SELECT video_id, category FROM hk_videos WHERE video_id=?", (vid,),
                ).fetchone()
                if not row:
                    continue
                category = (row[1] or "uncategorised").strip()
                out_dir = _download_dir() / category / vid
                out_dir.mkdir(parents=True, exist_ok=True)

                logger.info("Downloading %s (category=%s) → %s", vid, category, out_dir)
                _mark_downloading(conn, vid)

                try:
                    # download video + audio + thumbnail + meta
                    video_file = out_dir / f"{vid}.mp4"
                    audio_file = out_dir / f"{vid}.m4a"
                    thumbnail_file = out_dir / f"{vid}.jpg"
                    meta_file = out_dir / f"{vid}.video_info.json"

                    download_hk_file(vid, "video", video_file)
                    download_hk_file(vid, "audio", audio_file)
                    try:
                        download_hk_file(vid, "thumbnail", thumbnail_file)
                    except Exception:
                        thumbnail_file = Path("")

                    # download metadata JSON
                    try:
                        meta_data = download_hk_meta(vid)
                        meta_file.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    except Exception as exc:
                        logger.warning("Meta download failed for %s: %s", vid, exc)
                        meta_file = Path("")

                    # merge video + audio → merged.mp4
                    merged_file = out_dir / f"{vid}_merged.mp4"
                    merge_video_audio(video_file, audio_file, merged_file)
                    summary["merged"] += 1

                    # after successful merge, delete original separate files
                    video_file.unlink(missing_ok=True)
                    audio_file.unlink(missing_ok=True)

                    file_size = merged_file.stat().st_size if merged_file.exists() else 0
                    _mark_downloaded(
                        conn, vid, str(merged_file), file_size,
                        str(thumbnail_file), str(meta_file),
                    )
                    summary["downloaded"] += 1
                    logger.info("Download+merge OK: %s size=%d", vid, file_size)

                    # notify HK server to delete (video already confirmed downloaded locally)
                    try:
                        if delete_hk_video(vid):
                            summary["deleted_hk"] += 1
                            logger.info("Deleted from HK: %s", vid)
                    except Exception as exc:
                        logger.warning("HK delete failed for %s: %s", vid, exc)

                except Exception as exc:
                    # clean up partial downloads
                    for f in out_dir.glob("*"):
                        if f.is_file():
                            try:
                                f.unlink()
                            except OSError:
                                pass
                    _mark_failed(conn, vid, str(exc))
                    summary["failed"] += 1
                    logger.warning("Download/merge failed: %s err=%s", vid, exc)

                # wait between downloads
                if HK_DOWNLOAD_INTERVAL_SEC > 0 and vid != new_ids[-1]:
                    time.sleep(HK_DOWNLOAD_INTERVAL_SEC)

        _record_sync_log(conn, summary["new"], summary["downloaded"])
    except Exception as exc:
        logger.error("Sync cycle failed: %s", exc, exc_info=True)
        summary["error"] = str(exc)
    finally:
        _sync_lock.release()

    logger.info(
        "=== HK sync done: new=%d downloaded=%d merged=%d deleted_hk=%d failed=%d ===",
        summary["new"], summary["downloaded"], summary["merged"], summary["deleted_hk"], summary["failed"],
    )
    return summary


def publish_pending(
    account: str | None = None,
    interval_min: int = 30,
) -> dict[str, Any]:
    """Upload all locally-downloaded pending videos to Bilibili.

    Videos are published with interval_min minutes between each upload.
    """
    summary: dict[str, Any] = {"published": 0, "failed": 0, "skipped": 0}
    conn = _get_conn()
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT * FROM hk_videos
        WHERE download_status='downloaded' AND upload_status='pending'
        ORDER BY score DESC
        """,
    ).fetchall()

    if not rows:
        logger.info("No pending videos to publish")
        conn.close()
        return summary

    logger.info("Publish queue: %d videos", len(rows))

    for i, row in enumerate(rows):
        v = dict(row)
        vid = v["video_id"]
        category = str(v.get("category", "") or "")
        title = str(v.get("title", "") or "")
        url = str(v.get("url", "") or "")
        merged_path = Path(str(v.get("file_path", "") or ""))

        if not merged_path.exists():
            logger.warning("Merged file missing for %s: %s", vid, merged_path)
            _mark_upload_failed(conn, vid, "Merged file not found on disk")
            summary["skipped"] += 1
            continue

        # Build Bilibili metadata — use AI to generate Chinese content
        tid = BILIBILI_TID_MAP.get(category, 174)
        tags = BILIBILI_TAG_MAP.get(category, ["搬运", "YouTube"])

        # Load meta JSON and generate Chinese description
        meta_path = Path(str(v.get("meta_path", "") or ""))
        if meta_path.exists():
            try:
                import json as _json
                meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                from ai_describe import generate_chinese_metadata
                cn = generate_chinese_metadata(meta, category)
                title = cn.get("title", str(v.get("title", "") or ""))
                desc = cn.get("description", "")
                tags = cn.get("tags", tags)
            except Exception as exc:
                logger.warning("AI describe failed for %s: %s, using raw", vid, exc)
                title = str(v.get("title", "") or "")
                desc = f"原视频: {url}\n频道: {v.get('channel_title', '') or 'N/A'}"
        else:
            title = str(v.get("title", "") or "")
            desc = f"原视频: {url}\n频道: {v.get('channel_title', '') or 'N/A'}"

        logger.info("Publishing to Bilibili: %s (%s)", title[:50], vid)

        try:
            upload_to_bilibili(
                video_path=merged_path,
                title=title,
                description=desc,
                tid=tid,
                tags=tags,
                account=account,
            )
            _mark_uploaded(conn, vid, "bilibili")
            summary["published"] += 1
            logger.info("Published OK: %s", vid)

            # Delete local merged video file to save disk space (keep DB record)
            try:
                merged_path.unlink(missing_ok=True)
                # also clean up thumbnail and meta files in same directory
                parent = merged_path.parent
                if parent.exists():
                    import shutil as _shutil
                    _shutil.rmtree(parent, ignore_errors=True)
                logger.info("Cleaned disk files for %s", vid)
            except Exception as exc:
                logger.warning("File cleanup failed for %s: %s", vid, exc)
        except Exception as exc:
            _mark_upload_failed(conn, vid, str(exc))
            summary["failed"] += 1
            logger.warning("Publish failed: %s err=%s", vid, exc)

        # wait between uploads
        if i < len(rows) - 1 and interval_min > 0:
            logger.info("Waiting %dmin before next publish...", interval_min)
            time.sleep(interval_min * 60)

    conn.close()
    logger.info("=== Publish done: published=%d failed=%d ===", summary["published"], summary["failed"])
    return summary


# ── background pollers ──

def run_hk_poller() -> threading.Thread:
    interval_sec = max(30, int(HK_POLL_INTERVAL_MINUTES) * 60)

    def _loop() -> None:
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
