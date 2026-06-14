from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.discovery.models import VideoCandidate
from app.discovery.repository import (
    get_pending_downloads,
    init_db,
    mark_download_failed,
    mark_downloaded,
    mark_downloading,
    upsert_candidates,
)
from app.discovery.scoring import dedupe_and_sort
from app.discovery.service import run_discovery_once
from app.disk_cleaner import cleanup_if_needed
from app.downloader import download_media
from app.settings import settings
from app.task_state import finish_task, try_start_task

logger = logging.getLogger(__name__)

CACHE_FILE = Path("runtime/discovery/candidates_cache.json")
CACHE_TTL_SEC = 86400  # 24 hours


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for f in path.rglob('*'):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def _load_cache() -> tuple[list[dict], bool]:
    """Return (raw_candidates, fresh). fresh=False means cache expired or missing."""
    if not CACHE_FILE.exists():
        return [], False
    try:
        age = time.time() - CACHE_FILE.stat().st_mtime
        if age > CACHE_TTL_SEC:
            logger.info("Cache expired (age=%.1fh)", age / 3600)
            return [], False
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        logger.info("Cache hit: %d candidates (age=%.1fh)", len(data), age / 3600)
        return data, True
    except Exception as exc:
        logger.warning("Cache read failed: %s", exc)
        return [], False


def _save_cache(raw: list[dict]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Cache saved: %d candidates", len(raw))


def _dicts_to_candidates(items: list[dict]) -> list[VideoCandidate]:
    out: list[VideoCandidate] = []
    for d in items:
        try:
            out.append(VideoCandidate(**d))
        except Exception:
            continue
    return out


def _candidates_to_dicts(candidates: list[VideoCandidate]) -> list[dict]:
    return [asdict(c) for c in candidates]


def run_discovery_and_download(*, task_started: bool = False) -> dict[str, Any]:
    if not task_started and not try_start_task("discovery_download"):
        logger.info("Discovery/download task already running, skipping")
        return {"skipped": True, "reason": "task_running"}

    summary: dict[str, Any] = {
        "discovered": 0, "persisted": 0, "downloaded": 0,
        "failed": 0, "expired": 0, "cached": False,
    }

    try:
        db_path = settings.discovery_db_path.resolve()
        init_db(db_path)
        top_n = settings.discovery_top_n

        # 1. Discovery — cache-first
        cached_raw, fresh = _load_cache()

        if fresh:
            # Re-score from cache, pick new TopN
            raw = _dicts_to_candidates(cached_raw)
            selected = dedupe_and_sort(raw, top_n=top_n)
            summary["cached"] = True
            logger.info("Re-scored from cache: selected=%d (raw=%d)", len(selected), len(raw))
        else:
            # Full discovery — saves ALL raw candidates to cache
            raw, selected = run_discovery_once()
            summary["discovered"] = len(selected)
            if not selected:
                logger.info("No candidates discovered.")
            else:
                # Save ALL raw to cache so future runs can re-score without searching
                _save_cache(_candidates_to_dicts(raw))

        # 2. Persist selected to DB
        if selected:
            count = upsert_candidates(db_path, selected)
            summary["persisted"] = count
            logger.info("Persisted %d candidates to DB", count)

        # 3. Download pending
        media_root = settings.download_media_dir.resolve()
        min_score = settings.discovery_download_min_score
        pending = get_pending_downloads(db_path, limit=50, min_score=min_score)
        logger.info("Download queue: %d candidates with score >= %.1f", len(pending), min_score)

        interval = settings.download_interval_sec

        for i, p in enumerate(pending):
            vid = p["video_id"]
            url = p["url"]
            category = p.get("category", "uncategorised") or "uncategorised"
            out_dir = media_root / category / vid
            out_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Downloading %s category=%s -> %s", vid, category, out_dir)
            mark_downloading(db_path, vid)

            try:
                download_media(
                    url=str(url),
                    out_dir=out_dir,
                    cookie_file=settings.cookie_file,
                    proxy_url=settings.ytdlp_proxy,
                    playlist_strategy=settings.playlist_strategy,
                )
                total_size = _dir_size(out_dir)
                mark_downloaded(db_path, vid, str(out_dir), total_size)
                summary["downloaded"] += 1
                logger.info("Download OK: %s size=%d", vid, total_size)
            except Exception as exc:
                if out_dir.exists():
                    try:
                        shutil.rmtree(out_dir)
                    except OSError:
                        pass
                mark_download_failed(db_path, vid, str(exc))
                summary["failed"] += 1
                logger.warning("Download failed: %s err=%s", vid, exc)

            # 4. Cleanup after each download
            expired = cleanup_if_needed(
                db_path=db_path,
                media_dir=media_root,
                max_gb=settings.disk_max_storage_gb,
                max_days=settings.disk_max_retention_days,
            )
            if expired:
                summary["expired"] += expired

            # wait between downloads to avoid rate limiting
            if i < len(pending) - 1 and interval > 0:
                logger.info("Waiting %ds before next download...", interval)
                time.sleep(interval)

        logger.info(
            "=== Cycle complete: cached=%s discovered=%d persisted=%d downloaded=%d failed=%d expired=%d ===",
            summary["cached"], summary["discovered"], summary["persisted"],
            summary["downloaded"], summary["failed"], summary["expired"],
        )
        finish_task(summary=summary)
        return summary
    except Exception as exc:
        finish_task(summary=summary, error=str(exc))
        raise
