"""Process downloaded videos through the full dubbing pipeline.

Runs after download_service: transcribe → translate → bilingual merge → Chinese dubbing.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from app.discovery.repository import (
    get_pending_processes,
    init_db,
    mark_process_failed,
    mark_processed,
    mark_processing,
)
from app.pipeline import Pipeline
from app.settings import settings

logger = logging.getLogger(__name__)
_process_lock = threading.Lock()


def _find_media_in_dir(file_dir: str, video_id: str) -> tuple[Path, Path] | None:
    """Given a download directory, find the video (.mp4) and audio (.m4a) files."""
    d = Path(file_dir)
    if not d.is_dir():
        return None
    v_candidates = sorted(d.glob("*.mp4"))
    a_candidates = sorted(d.glob("*.m4a"))
    video = v_candidates[0] if v_candidates else None
    audio = a_candidates[0] if a_candidates else None
    if not video or not audio:
        return None
    return video, audio


def run_process_pipeline() -> dict[str, Any]:
    """Fetch downloaded-but-unprocessed videos and run the dubbing pipeline.

    Skips candidates whose media files are missing from disk.
    """
    if not _process_lock.acquire(blocking=False):
        logger.info("Process pipeline already running, skipping")
        return {"skipped": True, "reason": "already running"}

    summary: dict[str, Any] = {"processed": 0, "failed": 0, "skipped": 0}
    try:
        db_path = settings.discovery_db_path.resolve()
        init_db(db_path)
        max_retries = max(0, int(settings.process_max_retries))
        pending = get_pending_processes(db_path, max_retries=max_retries, limit=5)
        if not pending:
            logger.info("No videos pending processing")
            return summary

        logger.info("Process queue: %d candidates", len(pending))
        pipeline = Pipeline()

        for p in pending:
            vid = p["video_id"]
            file_dir = p.get("file_path", "") or ""
            title = p.get("title", vid)

            # Find media files on disk
            media = _find_media_in_dir(file_dir, vid)
            if media is None:
                logger.warning("Media files missing for %s (dir=%s), marking failed", vid, file_dir)
                mark_process_failed(db_path, vid, "Media files not found on disk")
                summary["skipped"] += 1
                continue

            video_path, audio_path = media
            logger.info("Processing %s (%s) video=%s audio=%s", vid, title, video_path, audio_path)
            mark_processing(db_path, vid)

            try:
                outputs = pipeline.run_with_media(
                    video_path=video_path,
                    audio_path=audio_path,
                    stem=vid,
                )
                mark_processed(
                    db_path,
                    vid,
                    bilingual_video=str(outputs.bilingual_video),
                    dubbed_video=str(outputs.dubbed_video) if outputs.dubbed_video else "",
                )
                summary["processed"] += 1
                logger.info(
                    "Process OK: %s bilingual=%s dubbed=%s",
                    vid, outputs.bilingual_video, outputs.dubbed_video,
                )
            except Exception as exc:
                mark_process_failed(db_path, vid, str(exc))
                summary["failed"] += 1
                logger.warning("Process failed: %s err=%s", vid, exc)

    finally:
        _process_lock.release()

    logger.info(
        "=== Process cycle done: processed=%d failed=%d skipped=%d ===",
        summary["processed"], summary["failed"], summary["skipped"],
    )
    return summary


def run_process_poller() -> threading.Thread:
    """Start a background daemon thread that polls for videos needing processing."""
    interval = max(10, int(settings.process_poll_interval_sec))

    def _loop() -> None:
        time.sleep(15)  # initial delay
        while True:
            try:
                run_process_pipeline()
            except Exception as exc:
                logger.error("Process poller error: %s", exc)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="process-poller")
    t.start()
    logger.info("Process poller started (interval=%d sec)", interval)
    return t
