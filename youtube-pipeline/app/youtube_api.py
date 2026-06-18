from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.config import Config


def parse_video_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/", 1)[0]
        if video_id:
            return video_id

    query = parse_qs(parsed.query)
    video_ids = query.get("v")
    if video_ids and video_ids[0]:
        return video_ids[0]

    if "/shorts/" in parsed.path:
        return parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]

    raise ValueError(f"Cannot parse YouTube video id from: {value}")


def create_retry(config: Config) -> Retry:
    return Retry(
        total=config.retries,
        connect=config.retries,
        read=config.retries,
        status=config.retries,
        backoff_factor=config.retry_backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )


def request_youtube(config: Config, path: str, params: dict[str, Any]) -> dict[str, Any]:
    if not config.youtube_api_key:
        raise RuntimeError("YOUTUBE_API_KEY is required in .env")

    url = f"{config.youtube_api_base.rstrip('/')}/{path.lstrip('/')}"
    proxies = {"http": config.proxy, "https": config.proxy} if config.proxy else None
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=create_retry(config))
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    with session:
        response = session.get(
            url,
            params={**params, "key": config.youtube_api_key},
            proxies=proxies,
            timeout=config.socket_timeout,
        )
        response.raise_for_status()
        return response.json()


def get_video_meta(config: Config, video_id_or_url: str) -> dict[str, Any]:
    video_id = parse_video_id(video_id_or_url)
    data = request_youtube(
        config,
        "videos",
        {
            "part": config.youtube_video_parts,
            "id": video_id,
            "maxResults": 1,
        },
    )
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Video not found: {video_id}")
    return items[0]


def search_videos(config: Config, keyword: str, max_results: int) -> list[dict[str, Any]]:
    search_data = request_youtube(
        config,
        "search",
        {
            "part": config.youtube_search_part,
            "q": keyword,
            "type": config.youtube_search_type,
            "order": config.youtube_search_order,
            "maxResults": max_results,
        },
    )
    video_ids = [
        item.get("id", {}).get("videoId")
        for item in search_data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    if not video_ids:
        return []

    videos_data = request_youtube(
        config,
        "videos",
        {
            "part": config.youtube_video_parts,
            "id": ",".join(video_ids),
            "maxResults": len(video_ids),
        },
    )
    return videos_data.get("items") or []
