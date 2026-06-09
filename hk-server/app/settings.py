from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # yt-dlp (dual-stream: bestvideo + bestaudio, merged locally)
    cookie_file: str = Field(default='')
    ytdlp_proxy: str = Field(default='')
    playlist_strategy: str = Field(default='first')
    ytdlp_video_format: str = Field(default='bestvideo[ext=mp4]')
    ytdlp_audio_format: str = Field(default='bestaudio[ext=m4a]')

    # logging
    log_level: str = Field(default='INFO')
    log_file: Path = Field(default=Path('runtime/logs/hk-server.log'))

    # ── discovery (daily candidate collection via yt-dlp) ──
    discovery_enabled: bool = Field(default=True)
    discovery_topic_types: str = Field(default='pets,beauty,funny')

    # per-topic keywords
    discovery_topic_ai_keywords: str = Field(default='AI,artificial intelligence,LLM,OpenAI,Anthropic,Google DeepMind')
    discovery_topic_tech_keywords: str = Field(default='technology,tech news,software engineering,cloud computing,startup tech')
    discovery_topic_digital_keywords: str = Field(default='gadgets,consumer tech,smartphone review,laptop review,digital products')
    discovery_topic_pets_keywords: str = Field(default='cute pets,funny cats,funny dogs,pet compilation,animals,cute animals,dog videos,cat videos')
    discovery_topic_beauty_keywords: str = Field(default='beauty,makeup tutorial,fashion,skincare,outfit,hairstyle,beauty tips')
    discovery_topic_funny_keywords: str = Field(default='funny videos,comedy,pranks,fails,viral funny,funny moments,try not to laugh,funny compilation')

    # per-topic language filter (comma-separated ISO 639-1 prefixes; empty = allow all)
    discovery_topic_ai_languages: str = Field(default='en')
    discovery_topic_tech_languages: str = Field(default='en')
    discovery_topic_digital_languages: str = Field(default='en')
    discovery_topic_pets_languages: str = Field(default='')
    discovery_topic_beauty_languages: str = Field(default='')
    discovery_topic_funny_languages: str = Field(default='')

    # generic extra keywords
    discovery_keywords: str = Field(default='')

    discovery_days_back: int = Field(default=7)
    discovery_max_results_per_keyword: int = Field(default=15)
    discovery_top_n: int = Field(default=5)
    discovery_min_views: int = Field(default=10000)
    discovery_min_comments: int = Field(default=0)  # yt-dlp flat search cannot provide comment_count
    discovery_min_duration_sec: int = Field(default=60)
    discovery_max_duration_sec: int = Field(default=1800)
    discovery_db_path: Path = Field(default=Path('runtime/discovery/discovery.db'))
    discovery_interval_minutes: int = Field(default=1440)

    # score threshold for auto-download (candidates with score >= this get downloaded)
    discovery_download_min_score: float = Field(default=5.0)

    # ── download storage ──
    download_media_dir: Path = Field(default=Path('runtime/downloads'))
    disk_max_storage_gb: float = Field(default=50.0)
    disk_max_retention_days: int = Field(default=7)

    # seconds between each video download to avoid triggering rate limits
    download_interval_sec: int = Field(default=180)

    # ── api server ──
    api_token: str = Field(default='')
    api_host: str = Field(default='0.0.0.0')
    api_port: int = Field(default=8503)


settings = Settings()
