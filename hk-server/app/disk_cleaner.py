from __future__ import annotations

import logging
import shutil
from pathlib import Path

from app.discovery.repository import (
    get_downloaded_oldest,
    get_expired_downloads,
    get_total_storage_bytes,
    mark_expired,
)

logger = logging.getLogger(__name__)


def cleanup_if_needed(
    db_path: Path,
    media_dir: Path,
    max_gb: float,
    max_days: int,
) -> int:
    """Delete oldest downloaded files until storage is under *max_gb* AND
    no files exceed *max_days* retention.  Returns number of files deleted.

    Only touches records with status='downloaded'.
    If the on-disk file is already missing the record is still marked expired.
    """
    deleted = 0
    max_bytes = int(max(0, max_gb) * 1024 ** 3)

    while True:
        total_bytes = get_total_storage_bytes(db_path)

        # collect expired records
        expired = get_expired_downloads(db_path, max_days=max_days, limit=100)

        # collect overflow records (oldest first)
        if max_bytes > 0 and total_bytes > max_bytes:
            overflow = get_downloaded_oldest(db_path, limit=100)
            expired_ids = {e['video_id'] for e in expired}
            overflow = [o for o in overflow if o['video_id'] not in expired_ids]
        else:
            overflow = []

        to_delete = expired + overflow

        if not to_delete:
            logger.info(
                'Cleanup: storage=%.1f/%.1f GB expired=%d overflow=%d — nothing to delete',
                total_bytes / (1024 ** 3), max_gb, len(expired), len(overflow),
            )
            break

        item = to_delete[0]
        vid = item['video_id']
        file_path_str = item.get('file_path', '')

        logger.info('Cleanup: deleting video_id=%s path=%s size=%d', vid, file_path_str, item.get('file_size', 0))

        # delete disk files
        if file_path_str:
            disk_path = Path(file_path_str)
            if disk_path.exists():
                try:
                    if disk_path.is_dir():
                        shutil.rmtree(disk_path)
                    else:
                        disk_path.unlink()
                except OSError as exc:
                    logger.warning('Cleanup: failed to delete disk files for %s: %s', vid, exc)
            else:
                logger.info('Cleanup: file_path not on disk for %s, marking expired', vid)

        # update DB
        mark_expired(db_path, vid)
        deleted += 1

    return deleted
