from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema


MEDIA_FIELDS = ("meta_path", "video_path", "audio_path", "poster_path", "merged_path")


def _bytes_to_gb(value: int) -> float:
    return round(value / 1024 / 1024 / 1024, 3)


def _parse_statuses(raw: str) -> set[str]:
    return {item.strip() for item in str(raw or "").split(",") if item.strip()}


def _safe_resolve(config: Config, raw_path: str) -> Path:
    return config.resolve_path(raw_path).resolve()


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _, files in os.walk(path):
        root_path = Path(root)
        for name in files:
            total += _file_size(root_path / name)
    return total


def _existing_disk_path(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    return current if current.exists() else Path.cwd()


def _parse_db_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    text = raw.replace("Z", "+00:00")
    for candidate in (text, text.replace(" ", "T")):
        try:
            value = datetime.fromisoformat(candidate)
            if value.tzinfo is not None:
                return value.astimezone().replace(tzinfo=None)
            return value
        except ValueError:
            continue
    return None


def _media_paths(config: Config, media_files: dict[str, Any] | None, output_dir: Path) -> list[dict[str, Any]]:
    paths: list[dict[str, Any]] = []
    if not media_files:
        return paths
    seen: set[Path] = set()
    for field in MEDIA_FIELDS:
        raw = str(media_files.get(field) or "")
        if not raw:
            continue
        path = _safe_resolve(config, raw)
        if path in seen:
            continue
        seen.add(path)
        paths.append(
            {
                "field": field,
                "path": str(path),
                "exists": path.exists() and path.is_file(),
                "size_bytes": _file_size(path),
                "inside_output_dir": _is_inside(path, output_dir),
            }
        )
    return paths


def get_storage_status(config: Config) -> dict[str, Any]:
    output_dir = config.resolve_path(str(config.output_dir)).resolve()
    usage = shutil.disk_usage(_existing_disk_path(output_dir))
    total_size = _directory_size(output_dir)
    by_status: dict[str, int] = {}
    candidates = _cleanup_candidates(config)
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        for video in repo.list_videos_with_media_files(limit=100000):
            media_size = sum(item["size_bytes"] for item in _media_paths(config, video, output_dir))
            by_status[str(video["status"])] = by_status.get(str(video["status"]), 0) + media_size

    max_bytes = int(float(config.storage_max_gb) * 1024 * 1024 * 1024)
    warn_bytes = int(float(config.storage_warn_gb) * 1024 * 1024 * 1024)
    min_free_bytes = int(float(config.storage_min_free_gb) * 1024 * 1024 * 1024)
    return {
        "output_dir": str(output_dir),
        "total_size_bytes": total_size,
        "total_size_gb": _bytes_to_gb(total_size),
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
        "disk_free_gb": _bytes_to_gb(usage.free),
        "disk_used_bytes": usage.used,
        "max_bytes": max_bytes,
        "warn_bytes": warn_bytes,
        "min_free_bytes": min_free_bytes,
        "over_max": bool(max_bytes and total_size > max_bytes),
        "over_warn": bool(warn_bytes and total_size > warn_bytes),
        "below_min_free": bool(min_free_bytes and usage.free < min_free_bytes),
        "cleanup_enabled": bool(config.storage_cleanup_enabled),
        "cleanup_statuses": sorted(_parse_statuses(config.storage_cleanup_statuses)),
        "retention_days": int(config.storage_retention_days),
        "by_status": [
            {"status": status, "size_bytes": size, "size_gb": _bytes_to_gb(size)}
            for status, size in sorted(by_status.items())
        ],
        "cleanup_preview": {
            "count": len(candidates),
            "size_bytes": sum(int(item["size_bytes"]) for item in candidates),
            "size_gb": _bytes_to_gb(sum(int(item["size_bytes"]) for item in candidates)),
            "items": candidates[:50],
        },
    }


def _cleanup_candidates(config: Config) -> list[dict[str, Any]]:
    output_dir = config.resolve_path(str(config.output_dir)).resolve()
    statuses = _parse_statuses(config.storage_cleanup_statuses)
    retention_days = int(config.storage_retention_days)
    published_retention_days = int(getattr(config, "storage_published_retention_days", 0) or 0)
    general_cutoff = datetime.now() - timedelta(days=retention_days) if retention_days > 0 else None
    candidates: list[dict[str, Any]] = []
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        for video in repo.list_videos_with_media_files(statuses=statuses, limit=100000):
            video_id = str(video["video_id"])
            status = str(video["status"])
            updated_at_raw = str(video.get("updated_at") or "")
            reference_at_raw = updated_at_raw
            reference_at = _parse_db_datetime(updated_at_raw)
            cleanup_reason = "video_updated_at"
            retention_for_video = retention_days
            cutoff = general_cutoff
            if status == "published" and published_retention_days > 0:
                retention_for_video = published_retention_days
                publish_record = repo.get_latest_publish_record_for_video(video_id)
                if publish_record:
                    reference_at_raw = str(publish_record.get("published_at") or publish_record.get("created_at") or "")
                    reference_at = _parse_db_datetime(reference_at_raw)
                    cleanup_reason = "published_at"
                else:
                    cleanup_reason = "published_video_updated_at"
                cutoff = datetime.now() - timedelta(days=published_retention_days)
            if cutoff and reference_at and reference_at > cutoff:
                continue
            paths = [
                item
                for item in _media_paths(config, video, output_dir)
                if item["exists"] and item["inside_output_dir"]
            ]
            size = sum(int(item["size_bytes"]) for item in paths)
            if not paths or size <= 0:
                continue
            candidates.append(
                {
                    "video_id": video_id,
                    "status": status,
                    "title": str(video.get("title") or ""),
                    "updated_at": str(video.get("updated_at") or ""),
                    "cleanup_reference_at": reference_at_raw,
                    "cleanup_reason": cleanup_reason,
                    "retention_days": retention_for_video,
                    "size_bytes": size,
                    "size_gb": _bytes_to_gb(size),
                    "paths": paths,
                }
            )
    candidates.sort(key=lambda item: (str(item["status"]) != "published", str(item["updated_at"])))
    return candidates


def _delete_candidate_media(repo: Repository, config: Config, candidate: dict[str, Any]) -> dict[str, Any]:
    video_id = str(candidate["video_id"])
    deleted_paths: list[str] = []
    cleared_fields: list[str] = []
    for item in candidate["paths"]:
        path = Path(str(item["path"]))
        try:
            if path.exists() and path.is_file():
                path.unlink()
            deleted_paths.append(str(path))
            cleared_fields.append(str(item["field"]))
        except OSError as exc:
            repo.create_event(
                video_id,
                None,
                "storage",
                "storage_media_cleanup_failed",
                f"Failed to delete media file: {path}",
                {"path": str(path), "error": str(exc)},
            )
    repo.clear_media_files(video_id, cleared_fields)
    video_dir = config.resolve_path(str(config.output_dir)).resolve() / video_id
    try:
        if video_dir.exists() and video_dir.is_dir() and not any(video_dir.iterdir()):
            video_dir.rmdir()
    except OSError:
        pass
    repo.create_event(
        video_id,
        None,
        "storage",
        "storage_media_cleaned",
        "Media files cleaned",
        {"paths": deleted_paths, "size_bytes": int(candidate["size_bytes"])},
    )
    return {**candidate, "deleted_paths": deleted_paths}


def cleanup_media(config: Config, dry_run: bool = True) -> dict[str, Any]:
    candidates = _cleanup_candidates(config)
    total_size = sum(int(item["size_bytes"]) for item in candidates)
    if dry_run:
        return {
            "status": "dry_run",
            "count": len(candidates),
            "size_bytes": total_size,
            "size_gb": _bytes_to_gb(total_size),
            "items": candidates,
        }

    cleaned: list[dict[str, Any]] = []
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        for candidate in candidates:
            cleaned.append(_delete_candidate_media(repo, config, candidate))
        conn.commit()
    return {
        "status": "cleaned",
        "count": len(cleaned),
        "size_bytes": total_size,
        "size_gb": _bytes_to_gb(total_size),
        "items": cleaned,
    }


def cleanup_video_media(config: Config, video_id: str, dry_run: bool = True, force: bool = False) -> dict[str, Any]:
    output_dir = config.resolve_path(str(config.output_dir)).resolve()
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        video = repo.get_video(video_id)
        if not video:
            raise KeyError(f"Video not found: {video_id}")
        status = str(video["status"])
        allowed_statuses = _parse_statuses(config.storage_cleanup_statuses)
        if status not in allowed_statuses and not force:
            raise RuntimeError(f"Video status is not cleanup eligible: {video_id} status={status}")
        paths = [
            item
            for item in _media_paths(config, repo.get_media_files(video_id), output_dir)
            if item["exists"] and item["inside_output_dir"]
        ]
        size = sum(int(item["size_bytes"]) for item in paths)
        candidate = {
            "video_id": video_id,
            "status": status,
            "title": str(video.get("title") or ""),
            "updated_at": str(video.get("updated_at") or ""),
            "size_bytes": size,
            "size_gb": _bytes_to_gb(size),
            "paths": paths,
        }
        if dry_run:
            return {"status": "dry_run", "item": candidate}
        cleaned = _delete_candidate_media(repo, config, candidate) if paths else candidate
        conn.commit()
        return {"status": "cleaned", "item": cleaned}
