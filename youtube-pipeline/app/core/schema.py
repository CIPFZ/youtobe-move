from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    duration INTEGER,
    view_count INTEGER,
    category TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 100,
    source_label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS video_metadata (
    video_id TEXT PRIMARY KEY,
    ytdlp_meta_json TEXT NOT NULL DEFAULT '',
    youtube_api_meta_json TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS media_files (
    video_id TEXT PRIMARY KEY,
    meta_path TEXT NOT NULL DEFAULT '',
    video_path TEXT NOT NULL DEFAULT '',
    audio_path TEXT NOT NULL DEFAULT '',
    poster_path TEXT NOT NULL DEFAULT '',
    merged_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS publish_drafts (
    video_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    tid INTEGER,
    tid_label TEXT NOT NULL DEFAULT '',
    tid_reason TEXT NOT NULL DEFAULT '',
    tid_source TEXT NOT NULL DEFAULT '',
    llm_raw_output TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(video_id, platform),
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS publish_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    account TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    published_at TEXT,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_records_success_once
ON publish_records(video_id, platform, account)
WHERE status = 'published';

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    locked_at TEXT,
    lock_owner TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    finished_at TEXT,
    next_run_at TEXT,
    error_type TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_type ON jobs(status, job_type);
CREATE INDEX IF NOT EXISTS idx_jobs_video_id ON jobs(video_id);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT,
    job_id INTEGER,
    module TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(video_id) REFERENCES videos(video_id) ON DELETE CASCADE,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_events_video_id_created_at ON events(video_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_module_id ON events(module, id);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(publish_drafts)").fetchall()
    }
    if "reviewed_at" not in columns:
        conn.execute("ALTER TABLE publish_drafts ADD COLUMN reviewed_at TEXT")
    if "review_note" not in columns:
        conn.execute("ALTER TABLE publish_drafts ADD COLUMN review_note TEXT NOT NULL DEFAULT ''")
    conn.execute("UPDATE publish_drafts SET status='pending' WHERE status IN ('ready', 'draft')")
    job_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
    }
    if "next_run_at" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN next_run_at TEXT")
    if "error_type" not in job_columns:
        conn.execute("ALTER TABLE jobs ADD COLUMN error_type TEXT NOT NULL DEFAULT ''")
    video_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(videos)").fetchall()
    }
    if "priority" not in video_columns:
        conn.execute("ALTER TABLE videos ADD COLUMN priority INTEGER NOT NULL DEFAULT 100")
    if "source_label" not in video_columns:
        conn.execute("ALTER TABLE videos ADD COLUMN source_label TEXT NOT NULL DEFAULT ''")
    conn.commit()
