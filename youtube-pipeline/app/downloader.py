from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import yt_dlp

from app.config import Config


logger = logging.getLogger("youtube-pipeline")


def json_default(value: Any) -> str:
    return str(value)


def write_meta(info: dict[str, Any], target: Path) -> None:
    logger.info("Writing metadata: %s", target)
    target.write_text(
        json.dumps(info, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )


def build_ytdlp_options(config: Config) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "noplaylist": True,
        "socket_timeout": config.socket_timeout,
        "retries": config.retries,
        "fragment_retries": config.fragment_retries,
        "retry_sleep_functions": {
            "http": lambda n: config.retry_backoff_factor * (2 ** (n - 1)),
            "fragment": lambda n: config.retry_backoff_factor * (2 ** (n - 1)),
        },
    }
    if config.cookie_file:
        opts["cookiefile"] = config.cookie_file
    if config.proxy:
        opts["proxy"] = config.proxy
    return opts


def extract_info(url: str, config: Config) -> dict[str, Any]:
    logger.info(
        "Extracting video metadata: url=%s proxy=%s cookie_file=%s",
        url,
        bool(config.proxy),
        bool(config.cookie_file),
    )
    opts = build_ytdlp_options(config)
    opts["skip_download"] = True

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp did not return video metadata.")
    if not info.get("id"):
        raise RuntimeError("yt-dlp metadata does not contain video id.")
    logger.info("Metadata extracted: id=%s title=%s", info.get("id"), info.get("title"))
    return info


def download_stream(
    url: str,
    out_dir: Path,
    output_name: str,
    format_selector: str,
    config: Config,
) -> Path:
    logger.info("Downloading %s stream: format=%s output_dir=%s", output_name, format_selector, out_dir)
    opts = build_ytdlp_options(config)
    opts.update({
        "format": format_selector,
        "outtmpl": str(out_dir / f"{output_name}.%(ext)s"),
        "overwrites": True,
    })

    before = set(out_dir.glob(f"{output_name}.*"))
    for old_file in before:
        if old_file.is_file():
            old_file.unlink()

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)

    files = sorted(
        path
        for path in out_dir.glob(f"{output_name}.*")
        if path.is_file() and not path.name.endswith(".part")
    )
    if not files:
        raise RuntimeError(f"{output_name} download finished but no output file was found.")
    logger.info("Downloaded %s stream: %s", output_name, files[0])
    return files[0]


def thumbnail_sort_key(item: dict[str, Any]) -> tuple[int, int, int, int]:
    width = int(item.get("width") or 0)
    height = int(item.get("height") or 0)
    preference = int(item.get("preference") or 0)
    return (width * height, width, height, preference)


def guess_extension(url: str, fallback: str = "jpg") -> str:
    clean_url = url.split("?", 1)[0]
    match = re.search(r"\.([a-zA-Z0-9]{2,5})$", clean_url)
    if not match:
        return fallback
    ext = match.group(1).lower()
    if ext == "jpeg":
        return "jpg"
    return ext


def download_poster(info: dict[str, Any], out_dir: Path, config: Config) -> Path | None:
    logger.info("Downloading poster: output_dir=%s", out_dir)
    thumbnails = info.get("thumbnails")
    if not isinstance(thumbnails, list):
        thumbnails = []

    candidates = [
        item
        for item in thumbnails
        if isinstance(item, dict) and str(item.get("url") or "").strip()
    ]
    if not candidates:
        thumb_url = str(info.get("thumbnail") or "").strip()
        if not thumb_url:
            return None
        candidates = [{"url": thumb_url}]

    best = max(candidates, key=thumbnail_sort_key)
    thumb_url = str(best["url"]).strip()
    ext = guess_extension(thumb_url)
    target = out_dir / f"poster.{ext}"

    proxies = {"http": config.proxy, "https": config.proxy} if config.proxy else None
    retry = Retry(
        total=config.retries,
        connect=config.retries,
        read=config.retries,
        status=config.retries,
        backoff_factor=config.retry_backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    try:
        with session:
            with session.get(
                thumb_url,
                headers={"User-Agent": "Mozilla/5.0"},
                proxies=proxies,
                timeout=config.socket_timeout,
                stream=True,
            ) as response:
                response.raise_for_status()
                with target.open("wb") as fp:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            fp.write(chunk)
    except requests.RequestException as exc:
        logger.warning("Poster download failed: %s", exc)
        return None

    logger.info("Downloaded poster: %s", target)
    return target


def merge_video_audio(video_id: str, video_path: Path, audio_path: Path, out_dir: Path, config: Config) -> Path:
    target = out_dir / f"{video_id}_merge.mp4"
    if target.exists():
        target.unlink()

    cmd = [
        config.ffmpeg_bin,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(target),
    ]
    logger.info("Merging video/audio: output=%s", target)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        logger.error("ffmpeg merge failed. stdout=%s stderr=%s", proc.stdout, proc.stderr)
        raise RuntimeError(f"ffmpeg merge failed with exit code {proc.returncode}")
    logger.info("Merged video/audio: %s", target)
    return target


def download_video_assets(url: str, config: Config) -> dict[str, str]:
    info = extract_info(url, config)
    video_id = str(info["id"])
    out_dir = config.output_dir / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    meta_path = out_dir / "meta.json"
    write_meta(info, meta_path)
    video_path = download_stream(url, out_dir, "video", config.video_format, config)
    audio_path = download_stream(url, out_dir, "audio", config.audio_format, config)
    poster_path = download_poster(info, out_dir, config)
    merged_path = merge_video_audio(video_id, video_path, audio_path, out_dir, config)

    return {
        "video_id": video_id,
        "title": str(info.get("title") or ""),
        "output_dir": str(out_dir),
        "meta": str(meta_path),
        "video": str(video_path),
        "audio": str(audio_path),
        "poster": str(poster_path) if poster_path else "",
        "merged": str(merged_path),
    }
