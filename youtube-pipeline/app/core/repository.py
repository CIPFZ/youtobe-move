from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.core.status import ensure_video_status, ensure_video_transition


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_video(
        self,
        video_id: str,
        source_url: str,
        status: str = "selected",
        title: str = "",
        channel: str = "",
        duration: int | None = None,
        view_count: int | None = None,
        category: str = "",
    ) -> dict[str, Any]:
        ensure_video_status(status)
        existing = self.get_video(video_id)
        if existing:
            self.conn.execute(
                """
                UPDATE videos
                SET source_url=?, title=COALESCE(NULLIF(?, ''), title),
                    channel=COALESCE(NULLIF(?, ''), channel),
                    duration=COALESCE(?, duration),
                    view_count=COALESCE(?, view_count),
                    category=COALESCE(NULLIF(?, ''), category),
                    updated_at=CURRENT_TIMESTAMP
                WHERE video_id=?
                """,
                (source_url, title, channel, duration, view_count, category, video_id),
            )
            self.create_event(video_id, None, "core", "video_upsert_existing", "Video already exists")
        else:
            self.conn.execute(
                """
                INSERT INTO videos (
                    video_id, source_url, title, channel, duration, view_count, category, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, source_url, title, channel, duration, view_count, category, status),
            )
            self.create_event(video_id, None, "core", "video_created", f"Video added with status={status}")
        self.conn.commit()
        result = self.get_video(video_id)
        if result is None:
            raise RuntimeError(f"Video upsert failed: {video_id}")
        return result

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM videos WHERE video_id=?", (video_id,)).fetchone()
        return row_to_dict(row)

    def list_videos(self, status: str | None = None, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        if status:
            ensure_video_status(status)
            rows = self.conn.execute(
                "SELECT * FROM videos WHERE status=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM videos ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_video_status(self, video_id: str, new_status: str, message: str = "", error: str = "") -> dict[str, Any]:
        video = self.get_video(video_id)
        if not video:
            raise KeyError(f"Video not found: {video_id}")
        old_status = str(video["status"])
        ensure_video_transition(old_status, new_status)
        self.conn.execute(
            """
            UPDATE videos
            SET status=?, last_error=?, updated_at=CURRENT_TIMESTAMP
            WHERE video_id=?
            """,
            (new_status, error, video_id),
        )
        self.create_event(
            video_id,
            None,
            "core",
            "status_changed",
            message or f"{old_status} -> {new_status}",
            {"from": old_status, "to": new_status, "error": error},
        )
        self.conn.commit()
        result = self.get_video(video_id)
        if result is None:
            raise RuntimeError(f"Video status update failed: {video_id}")
        return result

    def save_metadata(
        self,
        video_id: str,
        ytdlp_meta: dict[str, Any] | None = None,
        youtube_api_meta: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO video_metadata (video_id, ytdlp_meta_json, youtube_api_meta_json)
            VALUES (?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                ytdlp_meta_json=COALESCE(NULLIF(excluded.ytdlp_meta_json, ''), video_metadata.ytdlp_meta_json),
                youtube_api_meta_json=COALESCE(NULLIF(excluded.youtube_api_meta_json, ''), video_metadata.youtube_api_meta_json),
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                video_id,
                json.dumps(ytdlp_meta, ensure_ascii=False) if ytdlp_meta is not None else "",
                json.dumps(youtube_api_meta, ensure_ascii=False) if youtube_api_meta is not None else "",
            ),
        )
        self.create_event(video_id, None, "core", "metadata_saved", "Metadata saved")
        self.conn.commit()

    def save_media_files(
        self,
        video_id: str,
        meta_path: str = "",
        video_path: str = "",
        audio_path: str = "",
        poster_path: str = "",
        merged_path: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO media_files (video_id, meta_path, video_path, audio_path, poster_path, merged_path)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                meta_path=COALESCE(NULLIF(excluded.meta_path, ''), media_files.meta_path),
                video_path=COALESCE(NULLIF(excluded.video_path, ''), media_files.video_path),
                audio_path=COALESCE(NULLIF(excluded.audio_path, ''), media_files.audio_path),
                poster_path=COALESCE(NULLIF(excluded.poster_path, ''), media_files.poster_path),
                merged_path=COALESCE(NULLIF(excluded.merged_path, ''), media_files.merged_path),
                updated_at=CURRENT_TIMESTAMP
            """,
            (video_id, meta_path, video_path, audio_path, poster_path, merged_path),
        )
        self.create_event(video_id, None, "core", "media_files_saved", "Media file paths saved")
        self.conn.commit()

    def save_publish_draft(
        self,
        video_id: str,
        platform: str,
        title: str,
        description: str,
        tags: list[str],
        tid: int | None,
        tid_label: str = "",
        tid_reason: str = "",
        tid_source: str = "",
        llm_raw_output: str = "",
        status: str = "draft",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO publish_drafts (
                video_id, platform, title, description, tags_json, tid, tid_label,
                tid_reason, tid_source, llm_raw_output, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(video_id, platform) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                tags_json=excluded.tags_json,
                tid=excluded.tid,
                tid_label=excluded.tid_label,
                tid_reason=excluded.tid_reason,
                tid_source=excluded.tid_source,
                llm_raw_output=excluded.llm_raw_output,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                video_id,
                platform,
                title,
                description,
                json.dumps(tags, ensure_ascii=False),
                tid,
                tid_label,
                tid_reason,
                tid_source,
                llm_raw_output,
                status,
            ),
        )
        self.create_event(video_id, None, "core", "publish_draft_saved", f"Publish draft saved: {platform}")
        self.conn.commit()

    def save_publish_record(
        self,
        video_id: str,
        platform: str,
        account: str,
        status: str,
        external_id: str = "",
        published_at: str | None = None,
        error: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO publish_records (
                video_id, platform, account, external_id, status, published_at, error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (video_id, platform, account, external_id, status, published_at, error),
        )
        self.create_event(video_id, None, "core", "publish_record_saved", f"Publish record saved: {platform}/{status}")
        self.conn.commit()

    def create_job(
        self,
        job_type: str,
        video_id: str | None = None,
        status: str = "pending",
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO jobs (video_id, job_type, status, max_attempts, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (video_id, job_type, status, max_attempts, json.dumps(payload or {}, ensure_ascii=False)),
        )
        job_id = int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        self.create_event(video_id, job_id, "core", "job_created", f"Job created: {job_type}")
        self.conn.commit()
        return job_id

    def create_event(
        self,
        video_id: str | None,
        job_id: int | None,
        module: str,
        event_type: str,
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO events (video_id, job_id, module, event_type, message, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (video_id, job_id, module, event_type, message, json.dumps(payload or {}, ensure_ascii=False)),
        )

    def list_events(self, video_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if video_id:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE video_id=? ORDER BY id DESC LIMIT ?",
                (video_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]
