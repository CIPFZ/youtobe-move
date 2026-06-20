from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
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
        priority: int = 100,
        source_label: str = "",
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
                    priority=COALESCE(?, priority),
                    source_label=COALESCE(NULLIF(?, ''), source_label),
                    updated_at=CURRENT_TIMESTAMP
                WHERE video_id=?
                """,
                (source_url, title, channel, duration, view_count, category, priority, source_label, video_id),
            )
            self.create_event(video_id, None, "core", "video_upsert_existing", "Video already exists")
        else:
            self.conn.execute(
                """
                INSERT INTO videos (
                    video_id, source_url, title, channel, duration, view_count, category, priority, source_label, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (video_id, source_url, title, channel, duration, view_count, category, priority, source_label, status),
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

    def list_videos(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
        draft_status: str | None = None,
        error_type: str | None = None,
        platform: str = "bilibili",
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if status:
            ensure_video_status(status)
            filters.append("videos.status=?")
            params.append(status)
        if draft_status:
            filters.append(
                """
                EXISTS (
                    SELECT 1 FROM publish_drafts
                    WHERE publish_drafts.video_id = videos.video_id
                      AND publish_drafts.platform = ?
                      AND publish_drafts.status = ?
                )
                """
            )
            params.extend([platform, draft_status])
        if error_type:
            filters.append(
                """
                EXISTS (
                    SELECT 1 FROM jobs
                    WHERE jobs.video_id = videos.video_id
                      AND jobs.error_type = ?
                      AND jobs.id IN (
                          SELECT MAX(latest_jobs.id)
                          FROM jobs latest_jobs
                          WHERE latest_jobs.video_id = videos.video_id
                          GROUP BY latest_jobs.job_type
                      )
                )
                """
            )
            params.append(error_type)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        rows = self.conn.execute(
            f"""
            SELECT videos.*
            FROM videos
            {where}
            ORDER BY videos.priority ASC, videos.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def list_failures(
        self,
        limit: int = 50,
        offset: int = 0,
        job_type: str | None = None,
        error_type: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = ["videos.status='failed'"]
        params: list[Any] = []
        if job_type:
            filters.append("latest_job.job_type=?")
            params.append(job_type)
        if error_type:
            filters.append("latest_job.error_type=?")
            params.append(error_type)
        params.extend([limit, offset])
        rows = self.conn.execute(
            f"""
            SELECT
                videos.*,
                latest_job.id AS job_id,
                latest_job.job_type AS job_type,
                latest_job.status AS job_status,
                latest_job.attempts AS job_attempts,
                latest_job.max_attempts AS job_max_attempts,
                latest_job.error_type AS job_error_type,
                latest_job.error AS job_error,
                latest_job.next_run_at AS job_next_run_at,
                latest_job.updated_at AS job_updated_at
            FROM videos
            LEFT JOIN jobs latest_job ON latest_job.id = (
                SELECT jobs.id FROM jobs
                WHERE jobs.video_id = videos.video_id
                ORDER BY jobs.id DESC
                LIMIT 1
            )
            WHERE {" AND ".join(filters)}
            ORDER BY videos.updated_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
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

    def clear_media_files(self, video_id: str, fields: list[str]) -> None:
        allowed_fields = {"meta_path", "video_path", "audio_path", "poster_path", "merged_path"}
        selected = [field for field in fields if field in allowed_fields]
        if not selected:
            return
        assignments = ", ".join(f"{field}=''" for field in selected)
        self.conn.execute(
            f"""
            UPDATE media_files
            SET {assignments}, updated_at=CURRENT_TIMESTAMP
            WHERE video_id=?
            """,
            (video_id,),
        )
        self.create_event(
            video_id,
            None,
            "core",
            "media_files_cleared",
            "Media file paths cleared",
            {"fields": selected},
        )
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

    def update_publish_draft(
        self,
        video_id: str,
        platform: str,
        title: str,
        description: str,
        tags: list[str],
        tid: int | None,
        tid_label: str = "",
        tid_reason: str = "",
        tid_source: str = "manual",
        status: str = "pending",
    ) -> dict[str, Any]:
        if status not in {"pending", "approved", "rejected"}:
            raise ValueError(f"Unknown publish draft status: {status}")
        if not self.get_publish_draft(video_id, platform):
            raise KeyError(f"Publish draft not found: {video_id}/{platform}")
        self.conn.execute(
            """
            UPDATE publish_drafts
            SET title=?, description=?, tags_json=?, tid=?, tid_label=?,
                tid_reason=?, tid_source=?, status=?, reviewed_at=NULL,
                review_note='', updated_at=CURRENT_TIMESTAMP
            WHERE video_id=? AND platform=?
            """,
            (
                title,
                description,
                json.dumps(tags, ensure_ascii=False),
                tid,
                tid_label,
                tid_reason,
                tid_source,
                status,
                video_id,
                platform,
            ),
        )
        self.create_event(
            video_id,
            None,
            "core",
            "publish_draft_updated",
            f"Publish draft updated: {platform}",
            {"platform": platform, "tid": tid, "tid_source": tid_source, "status": status},
        )
        self.conn.commit()
        result = self.get_publish_draft(video_id, platform)
        if result is None:
            raise RuntimeError(f"Publish draft update failed: {video_id}/{platform}")
        return result

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
        if since.tzinfo is None:
            since_utc = datetime.fromtimestamp(since.timestamp(), UTC).replace(tzinfo=None)
        else:
            since_utc = since.astimezone(UTC).replace(tzinfo=None)
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count FROM publish_records
            WHERE platform=? AND account=? AND status='published'
              AND datetime(COALESCE(published_at, created_at)) >= datetime(?)
            """,
            (platform, account, since_utc.strftime("%Y-%m-%d %H:%M:%S")),
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

    def list_jobs(
        self,
        limit: int = 50,
        offset: int = 0,
        job_type: str | None = None,
        status: str | None = None,
        error_type: str | None = None,
    ) -> list[dict[str, Any]]:
        filters: list[str] = []
        params: list[Any] = []
        if job_type:
            filters.append("jobs.job_type=?")
            params.append(job_type)
        if status:
            if status not in JOB_STATUSES:
                raise ValueError(f"Unknown job status: {status}")
            filters.append("jobs.status=?")
            params.append(status)
        if error_type:
            filters.append("jobs.error_type=?")
            params.append(error_type)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.extend([limit, offset])
        rows = self.conn.execute(
            f"""
            SELECT
                jobs.*,
                videos.title AS video_title,
                videos.status AS video_status,
                videos.channel AS video_channel
            FROM jobs
            LEFT JOIN videos ON videos.video_id = jobs.video_id
            {where}
            ORDER BY jobs.id DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

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

    def count_locked_jobs(self) -> dict[str, int]:
        row = self.conn.execute(
            """
            SELECT
                SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                SUM(CASE WHEN locked_at IS NOT NULL THEN 1 ELSE 0 END) AS locked
            FROM jobs
            """
        ).fetchone()
        return {
            "running": int(row["running"] or 0),
            "locked": int(row["locked"] or 0),
        }

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

    def claim_pending_job(
        self,
        job_type: str,
        worker_id: str,
        lease_seconds: int,
        video_id: str | None = None,
    ) -> dict[str, Any] | None:
        lease_seconds = max(1, int(lease_seconds))
        lease_modifier = f"-{lease_seconds} seconds"
        filters = [
            "jobs.job_type=?",
            "jobs.status='pending'",
            "(jobs.next_run_at IS NULL OR datetime(jobs.next_run_at) <= datetime('now'))",
            "(jobs.locked_at IS NULL OR datetime(jobs.locked_at) <= datetime('now', ?))",
        ]
        params: list[Any] = [job_type, lease_modifier]
        if video_id:
            filters.append("jobs.video_id=?")
            params.append(video_id)
        else:
            eligible_statuses = {
                "download": ("selected", "failed"),
                "describe": ("downloaded", "failed"),
                "publish": ("ready_to_publish", "failed"),
            }.get(job_type, ("failed",))
            placeholders = ",".join("?" for _ in eligible_statuses)
            filters.append(f"videos.status IN ({placeholders})")
            params.extend(eligible_statuses)

        row = self.conn.execute(
            f"""
            SELECT jobs.* FROM jobs
            JOIN videos ON videos.video_id = jobs.video_id
            WHERE {" AND ".join(filters)}
            ORDER BY jobs.id ASC
            LIMIT 1
            """,
            params,
        ).fetchone()
        if not row:
            return None

        job_id = int(row["id"])
        updated = self.conn.execute(
            """
            UPDATE jobs
            SET locked_at=CURRENT_TIMESTAMP, lock_owner=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
              AND status='pending'
              AND (next_run_at IS NULL OR datetime(next_run_at) <= datetime('now'))
              AND (locked_at IS NULL OR datetime(locked_at) <= datetime('now', ?))
            """,
            (worker_id, job_id, lease_modifier),
        )
        if updated.rowcount != 1:
            self.conn.rollback()
            return None
        self.create_event(
            row["video_id"],
            job_id,
            "core",
            "job_claimed",
            f"Job claimed by {worker_id}",
            {"worker_id": worker_id, "lease_seconds": lease_seconds},
        )
        self.conn.commit()
        return self.get_job(job_id)

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
                SET status=?, finished_at=CURRENT_TIMESTAMP, error=?, error_type=?, next_run_at=?,
                    locked_at=NULL, lock_owner='', updated_at=CURRENT_TIMESTAMP
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
            SET status='pending', error=?, error_type=?, next_run_at=?,
                locked_at=NULL, lock_owner='', updated_at=CURRENT_TIMESTAMP
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

    def recover_stale_jobs(self, worker_id: str, lease_seconds: int) -> dict[str, Any]:
        lease_seconds = max(1, int(lease_seconds))
        cutoff = (datetime.now(UTC) - timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        recovered_jobs: list[dict[str, Any]] = []
        recovered_videos: list[dict[str, Any]] = []

        locked_pending = self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE status='pending' AND locked_at IS NOT NULL AND datetime(locked_at) <= datetime(?)
            ORDER BY id ASC
            """,
            (cutoff,),
        ).fetchall()
        for row in locked_pending:
            self.conn.execute(
                "UPDATE jobs SET locked_at=NULL, lock_owner='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (row["id"],),
            )
            recovered_jobs.append({"job_id": int(row["id"]), "job_type": row["job_type"], "status": "pending"})
            self.create_event(
                row["video_id"],
                int(row["id"]),
                "worker",
                "job_lock_released",
                "Stale pending job lock released",
                {"worker_id": worker_id, "previous_owner": row["lock_owner"], "locked_at": row["locked_at"]},
            )

        running = self.conn.execute(
            """
            SELECT * FROM jobs
            WHERE status='running'
              AND (locked_at IS NULL OR datetime(locked_at) <= datetime(?))
            ORDER BY id ASC
            """,
            (cutoff,),
        ).fetchall()
        target_statuses = {
            "download": "selected",
            "describe": "downloaded",
            "publish": "ready_to_publish",
        }
        for row in running:
            job_id = int(row["id"])
            video_id = str(row["video_id"] or "")
            job_type = str(row["job_type"])
            self.conn.execute(
                """
                UPDATE jobs
                SET status='pending', locked_at=NULL, lock_owner='', updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (job_id,),
            )
            recovered_jobs.append({"job_id": job_id, "job_type": job_type, "status": "running"})
            self.create_event(
                video_id or None,
                job_id,
                "worker",
                "stale_job_recovered",
                "Stale running job recovered to pending",
                {"worker_id": worker_id, "previous_owner": row["lock_owner"], "locked_at": row["locked_at"]},
            )

            target_status = target_statuses.get(job_type)
            if video_id and target_status:
                video = self.get_video(video_id)
                if video and str(video["status"]) in {"downloading", "describing", "publishing"}:
                    old_status = str(video["status"])
                    self.conn.execute(
                        """
                        UPDATE videos
                        SET status=?, updated_at=CURRENT_TIMESTAMP
                        WHERE video_id=?
                        """,
                        (target_status, video_id),
                    )
                    recovered_videos.append({"video_id": video_id, "from": old_status, "to": target_status})
                    self.create_event(
                        video_id,
                        job_id,
                        "worker",
                        "stale_video_recovered",
                        f"Stale video recovered: {old_status} -> {target_status}",
                        {"from": old_status, "to": target_status, "worker_id": worker_id},
                    )

        self.conn.commit()
        return {
            "recovered_jobs": recovered_jobs,
            "recovered_videos": recovered_videos,
            "count": len(recovered_jobs),
        }

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

    def list_events(
        self,
        video_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        module: str | None = None,
    ) -> list[dict[str, Any]]:
        if video_id and module:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE video_id=? AND module=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (video_id, module, limit, offset),
            ).fetchall()
        elif video_id:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE video_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (video_id, limit, offset),
            ).fetchall()
        elif module:
            rows = self.conn.execute(
                "SELECT * FROM events WHERE module=? ORDER BY id DESC LIMIT ? OFFSET ?",
                (module, limit, offset),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]
