from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ai_describe import parse_tid_options
from app.config import Config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.publisher import build_publish_payload, publish_payload_to_bilibili


logger = logging.getLogger("youtube-pipeline")

BILIBILI_PLATFORM = "bilibili"


def _ensure_job(repo: Repository, job_type: str, video: dict[str, Any], force: bool = False) -> int:
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


def describe_video(video_id: str, config: Config, force: bool = False) -> dict[str, Any]:
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

        job_id = _ensure_job(repo, "describe", video, force=force)
        repo.update_job_status(job_id, "running")
        try:
            repo.update_video_status(video_id, "describing", "Description generation started")
            repo.create_event(video_id, job_id, "publisher", "describe_started", "Description generation started")
            conn.commit()

            data_dir = _data_dir_from_media_files(repo.get_media_files(video_id))
            payload = build_publish_payload(data_dir, config)
            tid_selection = payload["tid_selection"]
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
                status="ready",
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
            repo.create_event(video_id, job_id, "publisher", "describe_failed", error, {"error": error})
            repo.update_video_status(video_id, "failed", "Description generation failed", error=error)
            repo.update_job_status(job_id, "failed", error=error)
            conn.commit()
            raise


def publish_video(video_id: str, config: Config, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
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
        job_id = _ensure_job(repo, "publish", video, force=force)
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
            repo.create_event(video_id, job_id, "publisher", "publish_failed", error, {"error": error})
            try:
                repo.update_video_status(video_id, "failed", "Publish failed", error=error)
            except ValueError:
                repo.conn.execute(
                    """
                    UPDATE videos
                    SET status='failed', last_error=?, updated_at=CURRENT_TIMESTAMP
                    WHERE video_id=?
                    """,
                    (error, video_id),
                )
            repo.update_job_status(job_id, "failed", error=error)
            conn.commit()
            raise


def publish_next(config: Config, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        job = repo.get_pending_job("publish")
        if job:
            video_id = str(job["video_id"])
        else:
            ready = repo.list_videos(status="ready_to_publish", limit=1)
            if not ready:
                return {"status": "empty", "message": "No ready videos waiting for publish"}
            video_id = str(ready[0]["video_id"])

    return publish_video(video_id, config, dry_run=dry_run, force=force)
