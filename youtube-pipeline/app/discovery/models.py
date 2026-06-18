from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.youtube_api import parse_youtube_duration_seconds


@dataclass(frozen=True)
class DiscoverySource:
    type: str
    name: str
    params: dict[str, Any]


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    source_type: str
    source_name: str
    source_query: str
    title: str
    channel_id: str
    channel: str
    duration: int | None
    view_count: int | None
    published_at: str
    category: str
    score: float
    source_url: str
    raw: dict[str, Any]


def candidate_from_youtube_item(
    item: dict[str, Any],
    source: DiscoverySource,
    source_query: str,
) -> VideoCandidate | None:
    video_id = str(item.get("id") or "").strip()
    if not video_id:
        return None
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    content = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
    stats = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}

    duration = parse_youtube_duration_seconds(str(content.get("duration") or ""))
    view_count_value = stats.get("viewCount")
    try:
        view_count = int(view_count_value) if view_count_value is not None else None
    except ValueError:
        view_count = None

    return VideoCandidate(
        video_id=video_id,
        source_type=source.type,
        source_name=source.name,
        source_query=source_query,
        title=str(snippet.get("title") or ""),
        channel_id=str(snippet.get("channelId") or ""),
        channel=str(snippet.get("channelTitle") or ""),
        duration=duration,
        view_count=view_count,
        published_at=str(snippet.get("publishedAt") or ""),
        category=str(snippet.get("categoryId") or ""),
        score=0.0,
        source_url=f"https://www.youtube.com/watch?v={video_id}",
        raw=item,
    )
