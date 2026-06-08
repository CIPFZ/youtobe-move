from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    work_dir: Path = Field(default=Path('runtime'))
    source_url: str = Field(default='')
    output_name: str = Field(default='final_output')
    metadata_dirname: str = Field(default='metadata')

    # yt-dlp
    cookie_file: str = Field(default='')
    ytdlp_proxy: str = Field(default='')
    playlist_strategy: str = Field(default='first')
    ytdlp_video_format: str = Field(default='bestvideo[ext=mp4][vcodec^=avc1]/bestvideo[ext=mp4]/bestvideo')
    ytdlp_audio_format: str = Field(default='bestaudio[ext=m4a]/bestaudio')

    # ffmpeg
    ffmpeg_path: str = Field(default='')


    # logging
    log_level: str = Field(default='INFO')
    log_file: Path = Field(default=Path('runtime/logs/pipeline.log'))

    # whisper
    whisper_model: str = Field(default='large-v3')
    whisper_model_source: str = Field(default='huggingface')
    whisper_modelscope_repo: str = Field(default='')
    whisper_model_cache_dir: Path = Field(default=Path('runtime/models'))
    whisper_download_to_local: bool = Field(default=True)
    whisper_download_proxy: str = Field(default='')
    whisper_model_fallback_to_modelscope: bool = Field(default=True)
    whisper_device: str = Field(default='auto')
    whisper_compute_type: str = Field(default='auto')
    whisper_language: str = Field(default='en')
    transcribe_use_vocals: bool = Field(default=False)
    transcribe_vocals_fallback_to_original: bool = Field(default=True)
    transcribe_separation_dirname: str = Field(default='transcribe_separated')

    # translation (OpenAI-compatible)
    openai_api_key: str = Field(default='')
    openai_base_url: str = Field(default='https://api.openai.com/v1')
    openai_model: str = Field(default='gpt-4o-mini')
    target_language: str = Field(default='zh-CN')
    translation_batch_size: int = Field(default=20)

    # ── discovery (daily candidate collection) ──
    discovery_enabled: bool = Field(default=False)
    youtube_api_key: str = Field(default='')
    discovery_topic_types: str = Field(default='ai,tech,digital')

    # per-topic keywords
    discovery_topic_ai_keywords: str = Field(default='AI,artificial intelligence,LLM,OpenAI,Anthropic,Google DeepMind')
    discovery_topic_tech_keywords: str = Field(default='technology,tech news,software engineering,cloud computing,startup tech')
    discovery_topic_digital_keywords: str = Field(default='gadgets,consumer tech,smartphone review,laptop review,digital products')
    discovery_topic_pets_keywords: str = Field(default='funny cats,cute dogs,pet videos,animal compilation')
    discovery_topic_beauty_keywords: str = Field(default='makeup tutorial,skincare routine,beauty tips,hair styling')
    discovery_topic_funny_keywords: str = Field(default='funny videos,comedy clips,pranks,fails')

    # per-topic language filter (comma-separated ISO 639-1 prefixes; empty = allow all)
    discovery_topic_ai_languages: str = Field(default='en')
    discovery_topic_tech_languages: str = Field(default='en')
    discovery_topic_digital_languages: str = Field(default='en')
    discovery_topic_pets_languages: str = Field(default='')
    discovery_topic_beauty_languages: str = Field(default='')
    discovery_topic_funny_languages: str = Field(default='')

    # generic extra keywords (no category affiliation)
    discovery_keywords: str = Field(default='')

    discovery_days_back: int = Field(default=3)
    discovery_max_results_per_keyword: int = Field(default=25)
    discovery_top_n: int = Field(default=20)
    discovery_min_views: int = Field(default=50000)
    discovery_min_comments: int = Field(default=100)
    discovery_min_duration_sec: int = Field(default=180)
    discovery_max_duration_sec: int = Field(default=3600)
    discovery_http_retries: int = Field(default=3)
    discovery_http_retry_backoff_sec: float = Field(default=1.2)
    discovery_db_path: Path = Field(default=Path('runtime/discovery/discovery.db'))
    discovery_interval_minutes: int = Field(default=60)

    # score threshold for auto-download (candidates with score >= this get downloaded)
    discovery_download_min_score: float = Field(default=10.0)

    # ── download storage ──
    download_media_dir: Path = Field(default=Path('runtime/downloads'))
    disk_max_storage_gb: float = Field(default=50.0)
    disk_max_retention_days: int = Field(default=30)

    # ── api server ──
    api_token: str = Field(default='')
    api_host: str = Field(default='0.0.0.0')
    api_port: int = Field(default=8503)

    # ── process pipeline (post-download dubbing) ──
    process_enabled: bool = Field(default=True)
    process_max_retries: int = Field(default=3)
    process_poll_interval_sec: int = Field(default=30)

    # unified pipeline
    pipeline_enable_dubbing: bool = Field(default=True)

    # dubbing pipeline (independent from subtitle-only pipeline)
    dubbing_work_dirname: str = Field(default='dubbing')
    dub_target_language: str = Field(default='zh-CN')
    dubbing_voice_volume: float = Field(default=1.0)
    dubbing_bgm_volume: float = Field(default=1.0)
    dubbing_max_speed: float = Field(default=1.2)
    dubbing_min_speed: float = Field(default=0.95)
    dubbing_max_chars_per_sec: float = Field(default=4.5)
    dubbing_segment_gap_sec: float = Field(default=0.6)
    dubbing_max_segment_duration_sec: float = Field(default=12.0)
    dubbing_crossfade_sec: float = Field(default=0.04)
    dubbing_preset: str = Field(default='default')
    dubbing_timing_mode: str = Field(default='relaxed')
    dubbing_max_advance_sec: float = Field(default=1.2)
    dubbing_min_gap_sec: float = Field(default=0.05)
    dubbing_reflow_subtitles: bool = Field(default=True)
    dubbing_subtitle_max_chars: int = Field(default=20)
    dubbing_subtitle_max_duration_sec: float = Field(default=3.6)
    dubbing_subtitle_max_gap_sec: float = Field(default=0.25)
    dubbing_trim_tts_silence: bool = Field(default=True)
    dubbing_tts_silence_threshold: float = Field(default=0.01)
    dubbing_tts_keep_lead_sec: float = Field(default=0.02)
    dubbing_tts_keep_tail_sec: float = Field(default=0.08)
    dubbing_preserve_full_text: bool = Field(default=True)
    dubbing_disable_time_stretch: bool = Field(default=True)

    # vocal separation
    separation_backend: str = Field(default='demucs')
    demucs_command: str = Field(default='demucs')
    demucs_model: str = Field(default='htdemucs_ft')
    demucs_device: str = Field(default='auto')
    demucs_cuda_fallback_to_cpu: bool = Field(default=True)
    demucs_cache_dir: Path = Field(default=Path('models/demucs'))

    # tts (OpenAI-compatible)
    tts_provider: str = Field(default='openai')
    tts_openai_model: str = Field(default='gpt-4o-mini-tts')
    tts_voice: str = Field(default='alloy')
    tts_edge_voice: str = Field(default='zh-CN-XiaoxiaoNeural')
    tts_voice_gender: str = Field(default='female')
    tts_edge_voice_female: str = Field(default='zh-CN-XiaoxiaoNeural')
    tts_edge_voice_male: str = Field(default='zh-CN-YunxiNeural')


settings = Settings()
