from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoCandidate:
    video_id: str
    url: str
    title: str
    channel_title: str
    published_at: str
    duration_sec: int
    view_count: int
    keyword: str
    category: str
    score: float
    raw_json: str
    score_json: str = '{}'
