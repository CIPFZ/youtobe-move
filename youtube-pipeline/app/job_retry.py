from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import Config
from app.core.repository import Repository
from app.error_policy import classify_error


RETRY_VIDEO_STATUS = {
    "download": "selected",
    "describe": "downloaded",
    "publish": "ready_to_publish",
}


def _next_run_at(config: Config, attempts: int) -> str:
    base = max(1, int(config.job_retry_base_seconds))
    max_delay = max(base, int(config.job_retry_max_seconds))
    delay = min(base * (2 ** max(0, attempts - 1)), max_delay)
    return (datetime.now(UTC) + timedelta(seconds=delay)).strftime("%Y-%m-%d %H:%M:%S")


def handle_job_failure(
    repo: Repository,
    job_id: int,
    job_type: str,
    video_id: str,
    error: str,
    config: Config,
    module: str,
    failed_message: str,
) -> dict[str, Any]:
    decision = classify_error(error, module=module)
    job = repo.get_job(job_id)
    attempts = int((job or {}).get("attempts") or 0)
    max_attempts = int((job or {}).get("max_attempts") or 1)

    if decision.retryable and attempts < max_attempts:
        next_run_at = _next_run_at(config, attempts)
        target_status = RETRY_VIDEO_STATUS.get(job_type, "failed")
        repo.force_video_status(video_id, target_status, f"{failed_message}; retry scheduled", error=error)
        repo.schedule_job_retry(job_id, error=error, error_type=decision.error_type, next_run_at=next_run_at)
        repo.create_event(
            video_id,
            job_id,
            module,
            f"{job_type}_retry_scheduled",
            f"Retry scheduled: {decision.error_type}",
            {
                "error": error,
                "error_type": decision.error_type,
                "attempts": attempts,
                "max_attempts": max_attempts,
                "next_run_at": next_run_at,
            },
        )
        return {
            "terminal": False,
            "error_type": decision.error_type,
            "next_run_at": next_run_at,
            "attempts": attempts,
            "max_attempts": max_attempts,
        }

    repo.create_event(
        video_id,
        job_id,
        module,
        f"{job_type}_failed",
        error,
        {
            "error": error,
            "error_type": decision.error_type,
            "retryable": decision.retryable,
            "attempts": attempts,
            "max_attempts": max_attempts,
        },
    )
    try:
        repo.update_video_status(video_id, "failed", failed_message, error=error)
    except ValueError:
        repo.conn.execute(
            """
            UPDATE videos
            SET status='failed', last_error=?, updated_at=CURRENT_TIMESTAMP
            WHERE video_id=?
            """,
            (error, video_id),
        )
    repo.update_job_status(job_id, "failed", error=error, error_type=decision.error_type)
    return {
        "terminal": True,
        "error_type": decision.error_type,
        "attempts": attempts,
        "max_attempts": max_attempts,
    }
