from __future__ import annotations

import logging
from typing import Any

import yt_dlp

from app.config import Config
from app.downloader import build_ytdlp_options


logger = logging.getLogger("youtube-pipeline")


def extract_media_info(url: str, config: Config) -> dict[str, Any]:
    opts = build_ytdlp_options(config)
    opts["skip_download"] = True
    opts["quiet"] = True
    opts["no_warnings"] = True
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp did not return video metadata.")
    if not info.get("id"):
        raise RuntimeError("yt-dlp metadata does not contain video id.")
    return info


def select_format(url: str, format_selector: str, config: Config) -> dict[str, Any]:
    opts = build_ytdlp_options(config)
    opts.update({
        "format": format_selector,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise RuntimeError(f"yt-dlp did not return selected format for selector={format_selector}")
    return info


def clean_format(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "format_id": item.get("format_id"),
        "format": item.get("format"),
        "format_note": item.get("format_note"),
        "ext": item.get("ext"),
        "protocol": item.get("protocol"),
        "url": item.get("url"),
        "manifest_url": item.get("manifest_url"),
        "width": item.get("width"),
        "height": item.get("height"),
        "resolution": item.get("resolution"),
        "fps": item.get("fps"),
        "vcodec": item.get("vcodec"),
        "acodec": item.get("acodec"),
        "dynamic_range": item.get("dynamic_range"),
        "filesize": item.get("filesize"),
        "filesize_approx": item.get("filesize_approx"),
        "tbr": item.get("tbr"),
        "vbr": item.get("vbr"),
        "abr": item.get("abr"),
        "asr": item.get("asr"),
        "audio_channels": item.get("audio_channels"),
        "language": item.get("language"),
        "quality": item.get("quality"),
        "source_preference": item.get("source_preference"),
        "preference": item.get("preference"),
        "http_headers": item.get("http_headers"),
    }


def require_direct_url(item: dict[str, Any], stream_name: str) -> None:
    if not item.get("url"):
        raise RuntimeError(f"{stream_name} format has no direct url.")


def get_media_urls(url: str, config: Config) -> dict[str, Any]:
    logger.info("Resolving media URLs: url=%s", url)
    base_info = extract_media_info(url, config)
    video_info = select_format(url, config.video_format, config)
    audio_info = select_format(url, config.audio_format, config)

    video = clean_format(video_info)
    audio = clean_format(audio_info)
    require_direct_url(video, "video")
    require_direct_url(audio, "audio")

    return {
        "video_id": str(base_info.get("id") or ""),
        "title": str(base_info.get("title") or ""),
        "webpage_url": str(base_info.get("webpage_url") or url),
        "video_selector": config.video_format,
        "audio_selector": config.audio_format,
        "video": video,
        "audio": audio,
    }
