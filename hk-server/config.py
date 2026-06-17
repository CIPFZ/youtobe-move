from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


DEFAULT_OUTPUT_DIR = Path("runtime/downloads")
DEFAULT_VIDEO_FORMAT = "bestvideo"
DEFAULT_AUDIO_FORMAT = "bestaudio"

ENV_OUTPUT_DIR = "OUTPUT_DIR"
ENV_VIDEO_FORMAT = "VIDEO_FORMAT"
ENV_AUDIO_FORMAT = "AUDIO_FORMAT"
ENV_PROXY = "PROXY"
ENV_COOKIE_FILE = "COOKIE_FILE"
ENV_SOCKET_TIMEOUT = "SOCKET_TIMEOUT"
ENV_RETRIES = "RETRIES"
ENV_FRAGMENT_RETRIES = "FRAGMENT_RETRIES"
ENV_LOG_LEVEL = "LOG_LEVEL"
ENV_LOG_FILE = "LOG_FILE"


class Config:
    def __init__(self) -> None:
        self.output_dir = Path(os.environ.get(ENV_OUTPUT_DIR, str(DEFAULT_OUTPUT_DIR)))
        self.video_format = os.environ.get(ENV_VIDEO_FORMAT, DEFAULT_VIDEO_FORMAT)
        self.audio_format = os.environ.get(ENV_AUDIO_FORMAT, DEFAULT_AUDIO_FORMAT)
        self.proxy = os.environ.get(ENV_PROXY, "")
        self.cookie_file = os.environ.get(ENV_COOKIE_FILE, "")
        self.socket_timeout = float(os.environ.get(ENV_SOCKET_TIMEOUT, "20"))
        self.retries = int(os.environ.get(ENV_RETRIES, "10"))
        self.fragment_retries = int(os.environ.get(ENV_FRAGMENT_RETRIES, "10"))
        self.log_level = os.environ.get(ENV_LOG_LEVEL, "INFO")
        self.log_file = os.environ.get(ENV_LOG_FILE, "")


def load_config() -> Config:
    load_dotenv(Path(".env"))
    return Config()
