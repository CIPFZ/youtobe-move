from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    url: str
    title: str
    description: str
    channel_id: str
    channel_title: str
    published_at: str
    language_hint: str
    duration_sec: int
    view_count: int
    comment_count: int
    like_count: int
    keyword: str
    category: str
    score: float
    raw_json: str
