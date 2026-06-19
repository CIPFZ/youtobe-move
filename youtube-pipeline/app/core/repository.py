from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from app.core.status import JOB_STATUSES, ensure_video_status, ensure_video_transition


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

    def count_videos_by_status(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM videos
            GROUP BY status
            ORDER BY status
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def count_active_queue(self) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM videos
            WHERE status IN ('selected', 'downloading', 'downloaded', 'describing', 'ready_to_publish', 'publishing')
            """
        ).fetchone()
        return int(row["count"])

    def update_video_basic_info(
        self,
        video_id: str,
        title: str = "",
        channel: str = "",
        duration: int | None = None,
        view_count: int | None = None,
        category: str = "",
    ) -> dict[str, Any]:
        if not self.get_video(video_id):
            raise KeyError(f"Video not found: {video_id}")
        self.conn.execute(
            """
            UPDATE videos
            SET title=COALESCE(NULLIF(?, ''), title),
                channel=COALESCE(NULLIF(?, ''), channel),
                duration=COALESCE(?, duration),
                view_count=COALESCE(?, view_count),
                category=COALESCE(NULLIF(?, ''), category),
                updated_at=CURRENT_TIMESTAMP
            WHERE video_id=?
            """,
            (title, channel, duration, view_count, category, video_id),
        )
        self.create_event(video_id, None, "core", "video_basic_info_saved", "Video basic info saved")
        self.conn.commit()
        result = self.get_video(video_id)
        if result is None:
            raise RuntimeError(f"Video basic info update failed: {video_id}")
        return result

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

    def force_video_status(self, video_id: str, new_status: str, message: str = "", error: str = "") -> dict[str, Any]:
        ensure_video_status(new_status)
        video = self.get_video(video_id)
        if not video:
            raise KeyError(f"Video not found: {video_id}")
        old_status = str(video["status"])
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
            "status_forced",
            message or f"{old_status} -> {new_status}",
            {"from": old_status, "to": new_status, "error": error},
        )
        self.conn.commit()
        result = self.get_video(video_id)
        if result is None:
            raise RuntimeError(f"Video forced status update failed: {video_id}")
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

    def get_media_files(self, video_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM media_files WHERE video_id=?", (video_id,)).fetchone()
        return row_to_dict(row)

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
                reviewed_at=NULL,
                review_note='',
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

    def get_publish_draft(self, video_id: str, platform: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM publish_drafts WHERE video_id=? AND platform=?",
            (video_id, platform),
        ).fetchone()
        return row_to_dict(row)

    def update_publish_draft_status(
        self,
        video_id: str,
        platform: str,
        status: str,
        note: str = "",
    ) -> dict[str, Any]:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"Unknown publish draft status: {status}")
        if not self.get_publish_draft(video_id, platform):
            raise KeyError(f"Publish draft not found: {video_id}/{platform}")
        self.conn.execute(
            """
            UPDATE publish_drafts
            SET status=?, reviewed_at=CURRENT_TIMESTAMP, review_note=?, updated_at=CURRENT_TIMESTAMP
            WHERE video_id=? AND platform=?
            """,
            (status, note, video_id, platform),
        )
        self.create_event(
            video_id,
            None,
            "core",
            "publish_draft_reviewed",
            f"Publish draft reviewed: {platform}/{status}",
            {"platform": platform, "status": status, "note": note},
        )
        self.conn.commit()
        result = self.get_publish_draft(video_id, platform)
        if result is None:
            raise RuntimeError(f"Publish draft status update failed: {video_id}/{platform}")
        return result

    def find_next_publishable_video(
        self,
        platform: str,
        account: str,
        require_approved: bool,
    ) -> dict[str, Any] | None:
        review_filter = "AND publish_drafts.status='approved'" if require_approved else "AND publish_drafts.status!='rejected'"
        row = self.conn.execute(
            f"""
            SELECT videos.* FROM videos
            JOIN publish_drafts ON publish_drafts.video_id = videos.video_id
            WHERE videos.status='ready_to_publish'
              AND publish_drafts.platform=?
              AND publish_drafts.title!=''
              AND publish_drafts.description!=''
              AND publish_drafts.tid IS NOT NULL
              AND publish_drafts.tid_source!='fallback'
              {review_filter}
              AND NOT EXISTS (
                  SELECT 1 FROM jobs
                  WHERE jobs.video_id = videos.video_id
                    AND jobs.job_type = 'publish'
                    AND jobs.status = 'pending'
                    AND jobs.next_run_at IS NOT NULL
                    AND datetime(jobs.next_run_at) > datetime('now')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM publish_records
                  WHERE publish_records.video_id = videos.video_id
                    AND publish_records.platform = ?
                    AND publish_records.account = ?
                    AND publish_records.status = 'published'
              )
            ORDER BY videos.updated_at ASC
            LIMIT 1
            """,
            (platform, platform, account),
        ).fetchone()
        return row_to_dict(row)

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

    def has_successful_publish_record(self, video_id: str, platform: str, account: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM publish_records
            WHERE video_id=? AND platform=? AND account=? AND status='published'
            LIMIT 1
            """,
            (video_id, platform, account),
        ).fetchone()
        return row is not None

    def count_publish_records_since(self, platform: str, account: str, since: datetime) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM publish_records
            WHERE platform=? AND account=? AND status='published'
              AND datetime(COALESCE(published_at, created_at)) >= datetime(?)
            """,
            (platform, account, since.isoformat()),
        ).fetchone()
        return int(row["count"])

    def get_latest_publish_record(self, platform: str, account: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM publish_records
            WHERE platform=? AND account=? AND status='published'
            ORDER BY datetime(COALESCE(published_at, created_at)) DESC
            LIMIT 1
            """,
            (platform, account),
        ).fetchone()
        return row_to_dict(row)

    def list_publish_records(self, video_id: str, platform: str | None = None) -> list[dict[str, Any]]:
        if platform:
            rows = self.conn.execute(
                """
                SELECT * FROM publish_records
                WHERE video_id=? AND platform=?
                ORDER BY id DESC
                """,
                (video_id, platform),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM publish_records WHERE video_id=? ORDER BY id DESC",
                (video_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def create_job(
        self,
        job_type: str,
        video_id: str | None = None,
        status: str = "pending",
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
        next_run_at: str | None = None,
    ) -> int:
        self.conn.execute(
            """
            INSERT INTO jobs (video_id, job_type, status, max_attempts, next_run_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (video_id, job_type, status, max_attempts, next_run_at, json.dumps(payload or {}, ensure_ascii=False)),
        )
        job_id = int(self.conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        self.create_event(video_id, job_id, "core", "job_created", f"Job created: {job_type}")
        self.conn.commit()
        return job_id

    def get_job(self, job_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row_to_dict(row)

    def get_latest_job(self, video_id: str, job_type: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE video_id=? AND job_type=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (video_id, job_type),
        ).fetchone()
        return row_to_dict(row)

    def get_latest_job_for_video(self, video_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE video_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (video_id,),
        ).fetchone()
        return row_to_dict(row)

    def count_jobs_by_type_status(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT job_type, status, COUNT(*) AS count
            FROM jobs
            GROUP BY job_type, status
            ORDER BY job_type, status
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_pending_job(
        self,
        job_type: str,
        video_id: str | None = None,
        include_future: bool = False,
    ) -> dict[str, Any] | None:
        next_run_filter = "" if include_future else "AND (next_run_at IS NULL OR datetime(next_run_at) <= datetime('now'))"
        if video_id:
            row = self.conn.execute(
                f"""
                SELECT * FROM jobs
                WHERE job_type=? AND status='pending' AND video_id=?
                  {next_run_filter}
                ORDER BY id ASC
                LIMIT 1
                """,
                (job_type, video_id),
            ).fetchone()
        else:
            eligible_statuses = {
                "download": ("selected", "failed"),
                "describe": ("downloaded", "failed"),
                "publish": ("ready_to_publish", "failed"),
            }.get(job_type, ("failed",))
            placeholders = ",".join("?" for _ in eligible_statuses)
            row = self.conn.execute(
                f"""
                SELECT jobs.* FROM jobs
                JOIN videos ON videos.video_id = jobs.video_id
                WHERE jobs.job_type=? AND jobs.status='pending' AND videos.status IN ({placeholders})
                  {next_run_filter.replace("next_run_at", "jobs.next_run_at")}
                ORDER BY jobs.id ASC
                LIMIT 1
                """,
                (job_type, *eligible_statuses),
            ).fetchone()
        return row_to_dict(row)

    def update_job_status(
        self,
        job_id: int,
        status: str,
        error: str = "",
        error_type: str = "",
        next_run_at: str | None = None,
    ) -> dict[str, Any]:
        if status not in JOB_STATUSES:
            raise ValueError(f"Unknown job status: {status}")
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")

        if status == "running":
            self.conn.execute(
                """
                UPDATE jobs
                SET status=?, attempts=attempts + 1, started_at=COALESCE(started_at, CURRENT_TIMESTAMP),
                    error=?, error_type=?, next_run_at=NULL, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, error, error_type, job_id),
            )
        elif status in {"succeeded", "failed", "cancelled"}:
            self.conn.execute(
                """
                UPDATE jobs
                SET status=?, finished_at=CURRENT_TIMESTAMP, error=?, error_type=?, next_run_at=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, error, error_type, next_run_at, job_id),
            )
        else:
            self.conn.execute(
                "UPDATE jobs SET status=?, error=?, error_type=?, next_run_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, error, error_type, next_run_at, job_id),
            )

        self.create_event(
            job["video_id"],
            job_id,
            "core",
            "job_status_changed",
            f"Job status changed: {job['status']} -> {status}",
            {"from": job["status"], "to": status, "error": error, "error_type": error_type, "next_run_at": next_run_at},
        )
        self.conn.commit()
        result = self.get_job(job_id)
        if result is None:
            raise RuntimeError(f"Job status update failed: {job_id}")
        return result

    def schedule_job_retry(self, job_id: int, error: str, error_type: str, next_run_at: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if not job:
            raise KeyError(f"Job not found: {job_id}")
        self.conn.execute(
            """
            UPDATE jobs
            SET status='pending', error=?, error_type=?, next_run_at=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (error, error_type, next_run_at, job_id),
        )
        self.create_event(
            job["video_id"],
            job_id,
            "core",
            "job_retry_scheduled",
            f"Job retry scheduled: {error_type}",
            {"error": error, "error_type": error_type, "next_run_at": next_run_at},
        )
        self.conn.commit()
        result = self.get_job(job_id)
        if result is None:
            raise RuntimeError(f"Job retry schedule failed: {job_id}")
        return result

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
