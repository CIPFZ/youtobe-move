from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import Config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.downloader import download_video_assets
from app.job_retry import handle_job_failure


logger = logging.getLogger("youtube-pipeline")


def _existing_merged_file(repo: Repository, video_id: str) -> Path | None:
    files = repo.get_media_files(video_id)
    if not files:
        return None
    merged_path = str(files.get("merged_path") or "")
    if not merged_path:
        return None
    path = Path(merged_path)
    return path if path.exists() else None


def _ensure_download_job(
    repo: Repository,
    video: dict[str, Any],
    force: bool,
    worker_id: str | None = None,
    lease_seconds: int = 1800,
    claimed_job_id: int | None = None,
) -> int:
    if claimed_job_id is not None:
        return claimed_job_id

    if worker_id and not force:
        claimed = repo.claim_pending_job("download", worker_id, lease_seconds, video_id=str(video["video_id"]))
        if claimed:
            return int(claimed["id"])
        if repo.get_pending_job("download", video_id=str(video["video_id"]), include_future=True):
            raise RuntimeError(f"Download job is not ready to run yet: {video['video_id']}")
        job_id = repo.create_job(
            "download",
            video_id=str(video["video_id"]),
            payload={"url": video["source_url"], "force": force},
        )
        claimed = repo.claim_pending_job("download", worker_id, lease_seconds, video_id=str(video["video_id"]))
        if not claimed:
            raise RuntimeError(f"Download job could not be claimed: {job_id}")
        return int(claimed["id"])

    pending = repo.get_pending_job("download", video_id=str(video["video_id"]))
    if pending and not force:
        return int(pending["id"])
    return repo.create_job(
        "download",
        video_id=str(video["video_id"]),
        payload={"url": video["source_url"], "force": force},
    )


def _event_writer(repo: Repository, video_id: str, job_id: int):
    def write(event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        repo.create_event(video_id, job_id, "downloader", event_type, message, payload)
        repo.conn.commit()

    return write


def download_video_from_db(
    video_id: str,
    config: Config,
    force: bool = False,
    worker_id: str | None = None,
    claimed_job_id: int | None = None,
) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        video = repo.get_video(video_id)
        if not video:
            raise KeyError(f"Video not found: {video_id}")

        existing_merged = _existing_merged_file(repo, video_id)
        if existing_merged and str(video["status"]) == "downloaded" and not force:
            repo.create_event(
                video_id,
                None,
                "downloader",
                "download_skipped",
                "Merged file already exists",
                {"merged_path": str(existing_merged)},
            )
            conn.commit()
            return {
                "video_id": video_id,
                "status": "skipped",
                "reason": "already_downloaded",
                "merged": str(existing_merged),
            }

        job_id = _ensure_download_job(
            repo,
            video,
            force,
            worker_id=worker_id,
            lease_seconds=getattr(config, "job_lease_seconds", 1800),
            claimed_job_id=claimed_job_id,
        )
        repo.update_job_status(job_id, "running")
        try:
            repo.update_video_status(video_id, "downloading", "Download started")
            repo.create_event(video_id, job_id, "downloader", "download_started", "Download started")
            conn.commit()

            result = download_video_assets(
                str(video["source_url"]),
                config,
                event_callback=_event_writer(repo, video_id, job_id),
            )
            downloaded_id = str(result["video_id"])
            if downloaded_id != video_id:
                raise RuntimeError(f"Downloaded video id mismatch: expected={video_id} actual={downloaded_id}")

            repo.update_video_basic_info(
                video_id,
                title=str(result.get("title") or ""),
                channel=str(result.get("channel") or ""),
                duration=result.get("duration"),
                view_count=result.get("view_count"),
                category=str(result.get("category") or ""),
            )
            repo.save_media_files(
                video_id,
                meta_path=str(result.get("meta") or ""),
                video_path=str(result.get("video") or ""),
                audio_path=str(result.get("audio") or ""),
                poster_path=str(result.get("poster") or ""),
                merged_path=str(result.get("merged") or ""),
            )
            repo.update_video_status(video_id, "downloaded", "Download completed")
            repo.update_job_status(job_id, "succeeded")
            repo.create_event(video_id, job_id, "downloader", "download_done", "Download completed", result)
            conn.commit()
            return {"job_id": job_id, **result, "status": "downloaded"}
        except Exception as exc:
            error = str(exc)
            logger.exception("Download failed: video_id=%s job_id=%s", video_id, job_id)
            handle_job_failure(
                repo,
                job_id=job_id,
                job_type="download",
                video_id=video_id,
                error=error,
                config=config,
                module="downloader",
                failed_message="Download failed",
            )
            conn.commit()
            raise


def download_next(config: Config, force: bool = False, worker_id: str | None = None) -> dict[str, Any]:
    claimed_job_id: int | None = None
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        if worker_id:
            job = repo.claim_pending_job("download", worker_id, getattr(config, "job_lease_seconds", 1800))
        else:
            job = repo.get_pending_job("download")
        if job:
            video_id = str(job["video_id"])
            claimed_job_id = int(job["id"])
        else:
            selected = repo.list_videos(status="selected", limit=50)
            runnable_video = next(
                (
                    video
                    for video in selected
                    if not repo.get_pending_job("download", video_id=str(video["video_id"]), include_future=True)
                ),
                None,
            )
            if not runnable_video:
                return {"status": "empty", "message": "No selected videos waiting for download"}
            video_id = str(runnable_video["video_id"])

    return download_video_from_db(
        video_id,
        config,
        force=force,
        worker_id=worker_id,
        claimed_job_id=claimed_job_id if worker_id else None,
    )
