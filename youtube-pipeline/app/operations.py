from __future__ import annotations

from typing import Any

from app.config import Config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema


RETRY_TARGETS = {
    "download": "selected",
    "describe": "downloaded",
    "publish": "ready_to_publish",
}


def pipeline_status(config: Config, events_limit: int = 20) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        return {
            "videos_by_status": repo.count_videos_by_status(),
            "jobs_by_type_status": repo.count_jobs_by_type_status(),
            "job_lock_status": repo.count_locked_jobs(),
            "active_queue_count": repo.count_active_queue(),
            "failed_videos": repo.list_videos(status="failed", limit=20),
            "recent_events": repo.list_events(limit=events_limit),
        }


def _infer_retry_job_type(repo: Repository, video_id: str) -> str:
    latest_job = repo.get_latest_job_for_video(video_id)
    if latest_job and str(latest_job["job_type"]) in RETRY_TARGETS:
        return str(latest_job["job_type"])

    media_files = repo.get_media_files(video_id)
    merged_path = str((media_files or {}).get("merged_path") or "")
    if not merged_path:
        return "download"

    draft = repo.get_publish_draft(video_id, "bilibili")
    if not draft:
        return "describe"
    return "publish"


def retry_video(video_id: str, config: Config, job_type: str | None = None) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        video = repo.get_video(video_id)
        if not video:
            raise KeyError(f"Video not found: {video_id}")
        if str(video["status"]) != "failed":
            raise RuntimeError(f"Only failed videos can be retried: {video_id} status={video['status']}")

        selected_job_type = job_type or _infer_retry_job_type(repo, video_id)
        if selected_job_type not in RETRY_TARGETS:
            raise RuntimeError(f"Unsupported retry job type: {selected_job_type}")

        target_status = RETRY_TARGETS[selected_job_type]
        updated = repo.update_video_status(video_id, target_status, f"Retry requested for {selected_job_type}")
        job_id = repo.create_job(
            selected_job_type,
            video_id=video_id,
            payload={"retry": True, "from_status": "failed", "target_status": target_status},
        )
        repo.create_event(
            video_id,
            job_id,
            "operations",
            "retry_requested",
            f"Retry requested: {selected_job_type}",
            {"job_type": selected_job_type, "target_status": target_status},
        )
        conn.commit()
        return {"video": updated, "job_id": job_id, "job_type": selected_job_type}


def skip_video(video_id: str, config: Config, force: bool = False) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        video = repo.get_video(video_id)
        if not video:
            raise KeyError(f"Video not found: {video_id}")
        current_status = str(video["status"])
        if current_status == "published":
            raise RuntimeError(f"Published videos cannot be skipped: {video_id}")
        if current_status in {"downloading", "describing", "publishing"} and not force:
            raise RuntimeError(f"Video is currently active; use --force to skip: {video_id} status={current_status}")

        if force:
            updated = repo.force_video_status(video_id, "skipped", "Video skipped by operator")
        else:
            updated = repo.update_video_status(video_id, "skipped", "Video skipped by operator")
        repo.create_event(video_id, None, "operations", "skip_requested", "Video skipped by operator")
        conn.commit()
        return {"video": updated}
