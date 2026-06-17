from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


class Config:
    def __init__(self) -> None:
        self.output_dir = Path(os.environ["OUTPUT_DIR"])
        self.video_format = os.environ["VIDEO_FORMAT"]
        self.audio_format = os.environ["AUDIO_FORMAT"]
        self.proxy = os.environ["PROXY"]
        self.cookie_file = os.environ["COOKIE_FILE"]
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
        self.log_level = os.environ["LOG_LEVEL"]
        self.log_file = os.environ["LOG_FILE"]


def load_config() -> Config:
    load_dotenv(Path(".env"))
    return Config()
