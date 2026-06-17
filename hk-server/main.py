from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any

import requests
import yt_dlp

from config import load_config
from logger import setup_logger


logger = logging.getLogger("hk-server")


def json_default(value: Any) -> str:
    return str(value)


def write_meta(info: dict[str, Any], target: Path) -> None:
    logger.info("Writing metadata: %s", target)
    target.write_text(
        json.dumps(info, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )


def extract_info(url: str, cookie_file: str = "", proxy: str = "") -> dict[str, Any]:
    logger.info("Extracting video metadata: url=%s proxy=%s cookie_file=%s", url, bool(proxy), bool(cookie_file))
    opts: dict[str, Any] = {
        "noplaylist": True,
        "skip_download": True,
    }
    if cookie_file:
        opts["cookiefile"] = cookie_file
    if proxy:
        opts["proxy"] = proxy

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
    cookie_file: str = "",
    proxy: str = "",
) -> Path:
    logger.info("Downloading %s stream: format=%s output_dir=%s", output_name, format_selector, out_dir)
    opts: dict[str, Any] = {
        "noplaylist": True,
        "format": format_selector,
        "outtmpl": str(out_dir / f"{output_name}.%(ext)s"),
        "overwrites": True,
    }
    if cookie_file:
        opts["cookiefile"] = cookie_file
    if proxy:
        opts["proxy"] = proxy

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


def download_poster(info: dict[str, Any], out_dir: Path, proxy: str = "") -> Path | None:
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

    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        with requests.get(
            thumb_url,
            headers={"User-Agent": "Mozilla/5.0"},
            proxies=proxies,
            timeout=30,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download one YouTube video's metadata, best video stream, best audio stream, and poster.",
    )
    parser.add_argument("url", help="YouTube video URL")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config()
    setup_logger(config.log_level, config.log_file)

    try:
        logger.info("Download job started: url=%s", args.url)
        info = extract_info(args.url, cookie_file=config.cookie_file, proxy=config.proxy)
        video_id = str(info["id"])
        out_dir = config.output_dir / video_id
        out_dir.mkdir(parents=True, exist_ok=True)

        meta_path = out_dir / "meta.json"
        write_meta(info, meta_path)

        video_path = download_stream(
            args.url,
            out_dir,
            "video",
            config.video_format,
            cookie_file=config.cookie_file,
            proxy=config.proxy,
        )
        audio_path = download_stream(
            args.url,
            out_dir,
            "audio",
            config.audio_format,
            cookie_file=config.cookie_file,
            proxy=config.proxy,
        )
        poster_path = download_poster(info, out_dir, proxy=config.proxy)

        result = {
            "video_id": video_id,
            "title": info.get("title") or "",
            "output_dir": str(out_dir),
            "meta": str(meta_path),
            "video": str(video_path),
            "audio": str(audio_path),
            "poster": str(poster_path) if poster_path else "",
        }
        logger.info("Download job completed: video_id=%s output_dir=%s", video_id, out_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        logger.exception("Download job failed: url=%s", args.url)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
