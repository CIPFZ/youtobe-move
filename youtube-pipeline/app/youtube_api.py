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


def get_videos_meta(config: Config, video_ids: list[str]) -> list[dict[str, Any]]:
    ids = [video_id for video_id in dict.fromkeys(video_ids) if video_id]
    if not ids:
        return []
    videos_data = request_youtube(
        config,
        "videos",
        {
            "part": config.youtube_video_parts,
            "id": ",".join(ids[:50]),
            "maxResults": min(len(ids), 50),
        },
    )
    return videos_data.get("items") or []


def search_videos(
    config: Config,
    keyword: str,
    max_results: int,
    order: str | None = None,
    channel_id: str | None = None,
    published_after: str | None = None,
    region_code: str | None = None,
    relevance_language: str | None = None,
    video_category_id: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "part": config.youtube_search_part,
        "q": keyword,
        "type": config.youtube_search_type,
        "order": order or config.youtube_search_order,
        "maxResults": max_results,
    }
    if channel_id:
        params["channelId"] = channel_id
    if published_after:
        params["publishedAfter"] = published_after
    if region_code:
        params["regionCode"] = region_code
    if relevance_language:
        params["relevanceLanguage"] = relevance_language
    if video_category_id:
        params["videoCategoryId"] = video_category_id
    search_data = request_youtube(
        config,
        "search",
        params,
    )
    video_ids = [
        item.get("id", {}).get("videoId")
        for item in search_data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    if not video_ids:
        return []

    return get_videos_meta(config, video_ids)


def get_trending_videos(
    config: Config,
    region_code: str,
    max_results: int,
    video_category_id: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "part": config.youtube_video_parts,
        "chart": "mostPopular",
        "regionCode": region_code,
        "maxResults": max_results,
    }
    if video_category_id:
        params["videoCategoryId"] = video_category_id
    data = request_youtube(config, "videos", params)
    return data.get("items") or []


def get_channel_uploads(config: Config, channel_id: str, max_results: int) -> list[dict[str, Any]]:
    search_data = request_youtube(
        config,
        "search",
        {
            "part": config.youtube_search_part,
            "channelId": channel_id,
            "type": config.youtube_search_type,
            "order": "date",
            "maxResults": max_results,
        },
    )
    video_ids = [
        item.get("id", {}).get("videoId")
        for item in search_data.get("items", [])
        if item.get("id", {}).get("videoId")
    ]
    return get_videos_meta(config, video_ids)


def get_channel_id_by_handle(config: Config, handle: str) -> str:
    handle = handle.strip()
    if not handle:
        raise ValueError("channel handle is empty")
    if not handle.startswith("@"):
        handle = f"@{handle}"
    data = request_youtube(
        config,
        "channels",
        {
            "part": "id",
            "forHandle": handle,
            "maxResults": 1,
        },
    )
    items = data.get("items") or []
    if not items:
        raise RuntimeError(f"Channel not found for handle: {handle}")
    channel_id = str(items[0].get("id") or "").strip()
    if not channel_id:
        raise RuntimeError(f"Channel id missing for handle: {handle}")
    return channel_id


def parse_youtube_duration_seconds(value: str) -> int | None:
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?",
        value or "",
    )
    if not match:
        return None
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = int(match.group("seconds") or 0)
    return days * 86400 + hours * 3600 + minutes * 60 + seconds
