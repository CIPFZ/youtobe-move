from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

from app.ai_describe import parse_tid_options
from app.config import Config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.job_retry import handle_job_failure
from app.publisher import build_publish_payload, publish_payload_to_bilibili


logger = logging.getLogger("youtube-pipeline")

BILIBILI_PLATFORM = "bilibili"
PUBLISH_MODES = {"manual", "approved_auto", "full_auto"}


def _ensure_publish_mode(config: Config) -> str:
    mode = str(config.publish_mode or "manual")
    if mode not in PUBLISH_MODES:
        raise RuntimeError(f"Unsupported PUBLISH_MODE: {mode}")
    return mode


def _parse_window_time(value: str) -> time | None:
    value = value.strip()
    if not value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return time(hour=int(hour), minute=int(minute))
    except ValueError as exc:
        raise RuntimeError(f"Invalid publish window time: {value}") from exc


def _check_publish_throttle(repo: Repository, config: Config) -> dict[str, Any]:
    now = datetime.now()
    start = _parse_window_time(str(config.publish_window_start or ""))
    end = _parse_window_time(str(config.publish_window_end or ""))
    if start and end:
        current = now.time()
        if start <= end:
            in_window = start <= current <= end
        else:
            in_window = current >= start or current <= end
        if not in_window:
            return {
                "ok": False,
                "reason": "outside_publish_window",
                "now": current.strftime("%H:%M"),
                "window_start": start.strftime("%H:%M"),
                "window_end": end.strftime("%H:%M"),
            }

    daily_limit = int(config.publish_daily_limit)
    if daily_limit > 0:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        published_today = repo.count_publish_records_since(BILIBILI_PLATFORM, config.bilibili_account, day_start)
        if published_today >= daily_limit:
            return {
                "ok": False,
                "reason": "daily_limit_reached",
                "published_today": published_today,
                "daily_limit": daily_limit,
            }

    min_interval = int(config.publish_min_interval_seconds)
    if min_interval > 0:
        latest = repo.get_latest_publish_record(BILIBILI_PLATFORM, config.bilibili_account)
        if latest:
            published_at_raw = str(latest.get("published_at") or latest.get("created_at") or "")
            try:
                published_at = datetime.fromisoformat(published_at_raw.replace("Z", "+00:00"))
                if published_at.tzinfo is not None:
                    published_at = published_at.astimezone().replace(tzinfo=None)
            except ValueError:
                published_at = None
            if published_at is not None:
                elapsed = now - published_at
                if elapsed < timedelta(seconds=min_interval):
                    return {
                        "ok": False,
                        "reason": "min_interval_not_elapsed",
                        "elapsed_seconds": int(elapsed.total_seconds()),
                        "min_interval_seconds": min_interval,
                    }

    return {"ok": True}


def _ensure_job(
    repo: Repository,
    job_type: str,
    video: dict[str, Any],
    force: bool = False,
    worker_id: str | None = None,
    lease_seconds: int = 1800,
    claimed_job_id: int | None = None,
) -> int:
    if claimed_job_id is not None:
        return claimed_job_id

    if worker_id and not force:
        claimed = repo.claim_pending_job(job_type, worker_id, lease_seconds, video_id=str(video["video_id"]))
        if claimed:
            return int(claimed["id"])
        if repo.get_pending_job(job_type, video_id=str(video["video_id"]), include_future=True):
            raise RuntimeError(f"{job_type} job is not ready to run yet: {video['video_id']}")
        job_id = repo.create_job(
            job_type,
            video_id=str(video["video_id"]),
            payload={"url": video["source_url"], "force": force},
        )
        claimed = repo.claim_pending_job(job_type, worker_id, lease_seconds, video_id=str(video["video_id"]))
        if not claimed:
            raise RuntimeError(f"{job_type} job could not be claimed: {job_id}")
        return int(claimed["id"])

    pending = repo.get_pending_job(job_type, video_id=str(video["video_id"]))
    if pending and not force:
        return int(pending["id"])
    return repo.create_job(
        job_type,
        video_id=str(video["video_id"]),
        payload={"url": video["source_url"], "force": force},
    )


def _data_dir_from_media_files(media_files: dict[str, Any] | None) -> Path:
    if not media_files:
        raise RuntimeError("Media files are missing")
    meta_path = Path(str(media_files.get("meta_path") or ""))
    merged_path = Path(str(media_files.get("merged_path") or ""))
    if not meta_path.exists():
        raise FileNotFoundError(f"meta.json is missing: {meta_path}")
    if not merged_path.exists():
        raise FileNotFoundError(f"merged video is missing: {merged_path}")
    return meta_path.parent


def _draft_to_publish_payload(draft: dict[str, Any], media_files: dict[str, Any], config: Config) -> dict[str, Any]:
    merged_path = Path(str(media_files.get("merged_path") or ""))
    if not merged_path.exists():
        raise FileNotFoundError(f"merged video is missing: {merged_path}")
    tags = json.loads(str(draft.get("tags_json") or "[]"))
    return {
        "account": config.bilibili_account,
        "video_file": str(merged_path),
        "title": str(draft["title"]),
        "description": str(draft["description"]),
        "tid": int(draft["tid"]),
        "tid_selection": {
            "tid": int(draft["tid"]),
            "label": str(draft.get("tid_label") or ""),
            "reason": str(draft.get("tid_reason") or ""),
            "source": str(draft.get("tid_source") or ""),
        },
        "tags": [str(tag) for tag in tags],
    }


def _validate_publish_draft(draft: dict[str, Any], config: Config) -> None:
    if not draft.get("title") or not draft.get("description"):
        raise RuntimeError("Publish draft title/description is missing")
    if draft.get("tid") is None:
        raise RuntimeError("Publish draft tid is missing")

    allowed_tids = parse_tid_options(config.bilibili_tid_options)
    tid = int(draft["tid"])
    if allowed_tids and tid not in allowed_tids:
        raise RuntimeError(f"Publish draft tid is not allowed: {tid}")
    if str(draft.get("tid_source") or "") == "fallback":
        raise RuntimeError("Publish draft tid came from fallback; regenerate or review before real publish")


def describe_video(
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

        existing = repo.get_publish_draft(video_id, BILIBILI_PLATFORM)
        if existing and str(video["status"]) == "ready_to_publish" and not force:
            repo.create_event(
                video_id,
                None,
                "publisher",
                "describe_skipped",
                "Publish draft already exists",
                {"platform": BILIBILI_PLATFORM},
            )
            conn.commit()
            return {"status": "skipped", "reason": "draft_exists", "draft": existing}

        job_id = _ensure_job(
            repo,
            "describe",
            video,
            force=force,
            worker_id=worker_id,
            lease_seconds=getattr(config, "job_lease_seconds", 1800),
            claimed_job_id=claimed_job_id,
        )
        repo.update_job_status(job_id, "running")
        try:
            repo.update_video_status(video_id, "describing", "Description generation started")
            repo.create_event(video_id, job_id, "publisher", "describe_started", "Description generation started")
            conn.commit()

            data_dir = _data_dir_from_media_files(repo.get_media_files(video_id))
            payload = build_publish_payload(data_dir, config)
            tid_selection = payload["tid_selection"]
            draft_status = "approved" if _ensure_publish_mode(config) == "full_auto" else "pending"
            repo.save_publish_draft(
                video_id=video_id,
                platform=BILIBILI_PLATFORM,
                title=str(payload["title"]),
                description=str(payload["description"]),
                tags=[str(tag) for tag in payload["tags"]],
                tid=int(payload["tid"]),
                tid_label=str(tid_selection.get("label") or ""),
                tid_reason=str(tid_selection.get("reason") or ""),
                tid_source=str(tid_selection.get("source") or ""),
                llm_raw_output=json.dumps(
                    {
                        "title": payload["title"],
                        "description": payload["description"],
                        "tags": payload["tags"],
                        "tid_selection": tid_selection,
                    },
                    ensure_ascii=False,
                ),
                status=draft_status,
            )
            repo.update_video_status(video_id, "ready_to_publish", "Publish draft generated")
            repo.update_job_status(job_id, "succeeded")
            repo.create_event(
                video_id,
                job_id,
                "publisher",
                "describe_done",
                "Publish draft generated",
                {"platform": BILIBILI_PLATFORM, "tid": int(payload["tid"])},
            )
            conn.commit()
            return {"status": "ready_to_publish", "job_id": job_id, "payload": payload}
        except Exception as exc:
            error = str(exc)
            logger.exception("Description generation failed: video_id=%s job_id=%s", video_id, job_id)
            handle_job_failure(
                repo,
                job_id=job_id,
                job_type="describe",
                video_id=video_id,
                error=error,
                config=config,
                module="describer",
                failed_message="Description generation failed",
            )
            conn.commit()
            raise


def publish_video(
    video_id: str,
    config: Config,
    dry_run: bool = False,
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

        if repo.has_successful_publish_record(video_id, BILIBILI_PLATFORM, config.bilibili_account) and not force:
            raise RuntimeError(f"Video has already been published to {BILIBILI_PLATFORM}: {video_id}")

        draft = repo.get_publish_draft(video_id, BILIBILI_PLATFORM)
        if not draft:
            raise RuntimeError(f"Publish draft is missing: {video_id}/{BILIBILI_PLATFORM}")
        media_files = repo.get_media_files(video_id)
        if dry_run:
            payload = _draft_to_publish_payload(draft, media_files or {}, config)
            payload["dry_run"] = True
            return {"status": "dry_run", "payload": payload}

        _validate_publish_draft(draft, config)
        job_id = _ensure_job(
            repo,
            "publish",
            video,
            force=force,
            worker_id=worker_id,
            lease_seconds=getattr(config, "job_lease_seconds", 1800),
            claimed_job_id=claimed_job_id,
        )
        repo.update_job_status(job_id, "running")
        try:
            repo.update_video_status(video_id, "publishing", "Publish started")
            repo.create_event(video_id, job_id, "publisher", "publish_started", "Publish started")
            conn.commit()

            payload = _draft_to_publish_payload(draft, media_files or {}, config)
            result = publish_payload_to_bilibili(payload, config, dry_run=False)
            repo.save_publish_record(
                video_id=video_id,
                platform=BILIBILI_PLATFORM,
                account=config.bilibili_account,
                status="published",
                published_at=datetime.now(UTC).isoformat(),
            )
            repo.update_video_status(video_id, "published", "Publish completed")
            repo.update_job_status(job_id, "succeeded")
            repo.create_event(video_id, job_id, "publisher", "publish_done", "Publish completed")
            conn.commit()
            return {"status": "published", "job_id": job_id, "payload": result}
        except Exception as exc:
            error = str(exc)
            logger.exception("Publish failed: video_id=%s job_id=%s", video_id, job_id)
            handle_job_failure(
                repo,
                job_id=job_id,
                job_type="publish",
                video_id=video_id,
                error=error,
                config=config,
                module="publisher",
                failed_message="Publish failed",
            )
            conn.commit()
            raise


def publish_next(
    config: Config,
    dry_run: bool = False,
    force: bool = False,
    worker_id: str | None = None,
) -> dict[str, Any]:
    mode = _ensure_publish_mode(config)
    if mode == "manual":
        return {"status": "skipped", "reason": "publish_mode_manual"}

    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)

        if not dry_run:
            throttle = _check_publish_throttle(repo, config)
            if not throttle["ok"]:
                return {"status": "skipped", **throttle}

        video = repo.find_next_publishable_video(
            BILIBILI_PLATFORM,
            config.bilibili_account,
            require_approved=mode == "approved_auto",
        )
        if not video:
            return {
                "status": "empty",
                "message": "No publishable videos waiting for automatic publish",
                "publish_mode": mode,
            }
        video_id = str(video["video_id"])
        claimed_job_id = None
        if worker_id:
            claimed = repo.claim_pending_job("publish", worker_id, getattr(config, "job_lease_seconds", 1800), video_id=video_id)
            if claimed:
                claimed_job_id = int(claimed["id"])
            elif repo.get_pending_job("publish", video_id=video_id, include_future=True):
                return {
                    "status": "empty",
                    "message": "No publishable videos waiting for automatic publish",
                    "publish_mode": mode,
                }

    return publish_video(
        video_id,
        config,
        dry_run=dry_run,
        force=force,
        worker_id=worker_id,
        claimed_job_id=claimed_job_id,
    )


def review_publish_draft(
    video_id: str,
    config: Config,
    status: str,
    note: str = "",
    platform: str = BILIBILI_PLATFORM,
) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        draft = repo.update_publish_draft_status(video_id, platform, status, note=note)
        conn.commit()
        return {"status": "ok", "draft": draft}


def describe_next(config: Config, force: bool = False, worker_id: str | None = None) -> dict[str, Any]:
    claimed_job_id: int | None = None
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        if worker_id:
            job = repo.claim_pending_job("describe", worker_id, getattr(config, "job_lease_seconds", 1800))
        else:
            job = repo.get_pending_job("describe")
        if job:
            video_id = str(job["video_id"])
            claimed_job_id = int(job["id"])
        else:
            downloaded = repo.list_videos(status="downloaded", limit=50)
            runnable_video = next(
                (
                    video
                    for video in downloaded
                    if not repo.get_pending_job("describe", video_id=str(video["video_id"]), include_future=True)
                ),
                None,
            )
            if not runnable_video:
                return {"status": "empty", "message": "No downloaded videos waiting for describe"}
            video_id = str(runnable_video["video_id"])

    return describe_video(
        video_id,
        config,
        force=force,
        worker_id=worker_id,
        claimed_job_id=claimed_job_id,
    )
