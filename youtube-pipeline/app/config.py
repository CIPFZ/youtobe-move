from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def _example_env_path(base_dir: Path) -> Path:
    local_example = base_dir / ".env.example"
    if local_example.exists():
        return local_example
    return Path(__file__).resolve().parents[1] / ".env.example"


class Config:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path.cwd()
        self.pipeline_enabled = os.environ["PIPELINE_ENABLED"].strip().lower() in {"1", "true", "yes", "on"}
        self.output_dir = Path(os.environ["OUTPUT_DIR"])
        self.db_path = self.resolve_path(os.environ["DB_PATH"])
        self.tmp_dir = self.resolve_path(os.environ["TMP_DIR"])
        self.video_format = os.environ["VIDEO_FORMAT"]
        self.audio_format = os.environ["AUDIO_FORMAT"]
        self.proxy = os.environ["PROXY"]
        self.cookie_file = os.environ["COOKIE_FILE"]
        self.ytdlp_remote_components = os.environ["YTDLP_REMOTE_COMPONENTS"]
        self.socket_timeout = float(os.environ["SOCKET_TIMEOUT"])
        self.retries = int(os.environ["RETRIES"])
        self.fragment_retries = int(os.environ["FRAGMENT_RETRIES"])
        self.retry_backoff_factor = float(os.environ["RETRY_BACKOFF_FACTOR"])
        self.youtube_api_key = os.environ["YOUTUBE_API_KEY"]
        self.youtube_api_base = os.environ["YOUTUBE_API_BASE"]
        self.youtube_video_parts = os.environ["YOUTUBE_VIDEO_PARTS"]
        self.youtube_search_part = os.environ["YOUTUBE_SEARCH_PART"]
        self.youtube_search_type = os.environ["YOUTUBE_SEARCH_TYPE"]
        self.youtube_search_order = os.environ["YOUTUBE_SEARCH_ORDER"]
        self.ffmpeg_bin = os.environ["FFMPEG_BIN"]
        self.social_auto_upload_dir = self.resolve_path(os.environ["SOCIAL_AUTO_UPLOAD_DIR"])
        self.bilibili_account = os.environ["BILIBILI_ACCOUNT"]
        self.bilibili_tid = int(os.environ["BILIBILI_TID"])
        self.bilibili_tid_options = os.environ["BILIBILI_TID_OPTIONS"]
        self.minimax_anthropic_base_url = os.environ["MINIMAX_ANTHROPIC_BASE_URL"].rstrip("/")
        self.minimax_anthropic_api_key = os.environ["MINIMAX_ANTHROPIC_API_KEY"]
        self.minimax_anthropic_model = os.environ["MINIMAX_ANTHROPIC_MODEL"]
        self.minimax_anthropic_version = os.environ["MINIMAX_ANTHROPIC_VERSION"]
        self.minimax_request_timeout = int(os.environ["MINIMAX_REQUEST_TIMEOUT"])
        self.minimax_max_tokens = int(os.environ["MINIMAX_MAX_TOKENS"])
        self.worker_interval_seconds = int(os.environ["WORKER_INTERVAL_SECONDS"])
        self.worker_cron = os.environ["WORKER_CRON"]
        self.worker_enable_discovery = os.environ["WORKER_ENABLE_DISCOVERY"].strip().lower() in {"1", "true", "yes", "on"}
        self.worker_enable_download = os.environ["WORKER_ENABLE_DOWNLOAD"].strip().lower() in {"1", "true", "yes", "on"}
        self.worker_enable_describe = os.environ["WORKER_ENABLE_DESCRIBE"].strip().lower() in {"1", "true", "yes", "on"}
        self.worker_discovery_min_queue_size = int(os.environ["WORKER_DISCOVERY_MIN_QUEUE_SIZE"])
        self.worker_discovery_source = os.environ["WORKER_DISCOVERY_SOURCE"].strip() or None
        self.worker_enable_publish = os.environ["WORKER_ENABLE_PUBLISH"].strip().lower() in {"1", "true", "yes", "on"}
        self.worker_publish_dry_run = os.environ["WORKER_PUBLISH_DRY_RUN"].strip().lower() in {"1", "true", "yes", "on"}
        self.job_lease_seconds = int(os.environ["JOB_LEASE_SECONDS"])
        self.job_retry_base_seconds = int(os.environ["JOB_RETRY_BASE_SECONDS"])
        self.job_retry_max_seconds = int(os.environ["JOB_RETRY_MAX_SECONDS"])
        self.publish_mode = os.environ["PUBLISH_MODE"]
        self.publish_min_interval_seconds = int(os.environ["PUBLISH_MIN_INTERVAL_SECONDS"])
        self.publish_daily_limit = int(os.environ["PUBLISH_DAILY_LIMIT"])
        self.publish_window_start = os.environ["PUBLISH_WINDOW_START"]
        self.publish_window_end = os.environ["PUBLISH_WINDOW_END"]
        self.storage_max_gb = float(os.environ["STORAGE_MAX_GB"])
        self.storage_warn_gb = float(os.environ["STORAGE_WARN_GB"])
        self.storage_min_free_gb = float(os.environ["STORAGE_MIN_FREE_GB"])
        self.storage_retention_days = int(os.environ["STORAGE_RETENTION_DAYS"])
        self.storage_published_retention_days = int(os.environ["STORAGE_PUBLISHED_RETENTION_DAYS"])
        self.storage_cleanup_enabled = os.environ["STORAGE_CLEANUP_ENABLED"].strip().lower() in {"1", "true", "yes", "on"}
        self.storage_cleanup_statuses = os.environ["STORAGE_CLEANUP_STATUSES"]
        self.web_host = os.environ["WEB_HOST"]
        self.web_port = int(os.environ["WEB_PORT"])
        self.discovery_sources_json = os.environ["DISCOVERY_SOURCES_JSON"]
        self.discovery_max_results_per_source = int(os.environ["DISCOVERY_MAX_RESULTS_PER_SOURCE"])
        self.discovery_min_duration_seconds = int(os.environ["DISCOVERY_MIN_DURATION_SECONDS"])
        self.discovery_max_duration_seconds = int(os.environ["DISCOVERY_MAX_DURATION_SECONDS"])
        self.discovery_min_view_count = int(os.environ["DISCOVERY_MIN_VIEW_COUNT"])
        self.discovery_title_blocklist = os.environ["DISCOVERY_TITLE_BLOCKLIST"]
        self.discovery_channel_allowlist = os.environ["DISCOVERY_CHANNEL_ALLOWLIST"]
        self.discovery_channel_blocklist = os.environ["DISCOVERY_CHANNEL_BLOCKLIST"]
        self.discovery_category_allowlist = os.environ["DISCOVERY_CATEGORY_ALLOWLIST"]
        self.discovery_category_blocklist = os.environ["DISCOVERY_CATEGORY_BLOCKLIST"]
        self.log_level = os.environ["LOG_LEVEL"]
        self.log_file = os.environ["LOG_FILE"]

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.base_dir / path


def load_config() -> Config:
    env_path = Path(".env").resolve()
    load_dotenv(_example_env_path(env_path.parent), override=False)
    load_dotenv(env_path, override=True)
    return Config(base_dir=env_path.parent)
