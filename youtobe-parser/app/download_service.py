from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from app.discovery.repository import (
    get_pending_downloads,
    init_db,
    mark_download_failed,
    mark_downloaded,
    mark_downloading,
    upsert_candidates,
)
from app.discovery.service import run_discovery_once
from app.disk_cleaner import cleanup_if_needed
from app.downloader import download_media
from app.settings import settings

logger = logging.getLogger(__name__)


def _dir_size(path: Path) -> int:
    """Return total size in bytes of all files under *path*."""
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


def run_discovery_and_download() -> dict[str, Any]:
    """Run one complete cycle: discovery -> persist -> download high-score -> cleanup.

    Returns a summary dict with counts.
    """
    summary: dict[str, Any] = {
        'discovered': 0,
        'persisted': 0,
        'downloaded': 0,
        'failed': 0,
        'cleaned': 0,
    }

    # 1. Discovery
    logger.info('=== Discovery cycle start ===')
    raw, selected = run_discovery_once()
    summary['discovered'] = len(selected)
    if not selected:
        logger.info('No candidates discovered.')
        return summary

    # 2. Persist
    db_path = settings.discovery_db_path.resolve()
    init_db(db_path)
    count = upsert_candidates(db_path, selected)
    summary['persisted'] = count
    logger.info('Persisted %d candidates to DB', count)

    # 3. Download high-score candidates
    media_root = settings.download_media_dir.resolve()
    min_score = settings.discovery_download_min_score
    pending = get_pending_downloads(db_path, limit=50, min_score=min_score)
    logger.info(
        'Download queue: %d candidates with score >= %.1f',
        len(pending), min_score,
    )

    for p in pending:
        vid = p['video_id']
        url = p['url']
        category = p.get('category', 'uncategorised') or 'uncategorised'

        # per-video output dir: runtime/downloads/{category}/{video_id}/
        out_dir = media_root / category / vid
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info('Downloading %s category=%s -> %s', vid, category, out_dir)
        mark_downloading(db_path, vid)

        try:
            result = download_media(
                url=str(url),
                out_dir=out_dir,
                cookie_file=settings.cookie_file,
                proxy_url=settings.ytdlp_proxy,
                playlist_strategy=settings.playlist_strategy,
            )
            # total size of downloaded files
            total_size = _dir_size(out_dir)
            mark_downloaded(db_path, vid, str(out_dir), total_size)
            summary['downloaded'] += 1
            logger.info('Download OK: %s size=%d', vid, total_size)
        except Exception as exc:
            # clean up partial download dir
            if out_dir.exists():
                try:
                    shutil.rmtree(out_dir)
                except OSError:
                    pass
            mark_download_failed(db_path, vid, str(exc))
            summary['failed'] += 1
            logger.warning('Download failed: %s err=%s', vid, exc)

        # 4. Cleanup after each download
        cleaned = cleanup_if_needed(
            db_path=db_path,
            media_dir=media_root,
            max_gb=settings.disk_max_storage_gb,
            max_days=settings.disk_max_retention_days,
        )
        if cleaned:
            summary['cleaned'] += cleaned

    logger.info(
        '=== Discovery cycle complete: discovered=%d persisted=%d downloaded=%d failed=%d cleaned=%d ===',
        summary['discovered'],
        summary['persisted'],
        summary['downloaded'],
        summary['failed'],
        summary['cleaned'],
    )
    return summary
