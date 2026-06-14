from __future__ import annotations

import math
from datetime import datetime, timezone

from app.discovery.models import VideoCandidate


def should_keep_candidate(
    *,
    view_count: int,
    duration_sec: int,
    min_views: int,
    min_duration_sec: int,
    max_duration_sec: int,
) -> bool:
    if view_count < min_views:
        return False
    if duration_sec < min_duration_sec:
        return False
    if duration_sec > max_duration_sec:
        return False
    return True


def compute_hot_score(view_count: int, published_at: str) -> float:
    """Rank candidates by real fields available from yt-dlp search."""
    views_term = math.log10(max(10, view_count))

    freshness_term = 0.0
    try:
        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00')).astimezone(timezone.utc)
        age_hours = max(1.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
        freshness_term = 24.0 / age_hours
    except Exception:
        freshness_term = 0.0

    return round(views_term + freshness_term, 6)


def dedupe_and_sort(candidates: list[VideoCandidate], top_n: int) -> list[VideoCandidate]:
    latest: dict[str, VideoCandidate] = {}
    for item in candidates:
        prev = latest.get(item.video_id)
        if prev is None or item.score > prev.score:
            latest[item.video_id] = item
    ordered = sorted(latest.values(), key=lambda x: x.score, reverse=True)
    return ordered[: max(1, top_n)]
