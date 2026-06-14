from __future__ import annotations

import math
from datetime import datetime, timezone

from app.discovery.models import VideoCandidate


def _csv_values(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(',') if item.strip()]


def should_keep_candidate(
    *,
    view_count: int,
    duration_sec: int,
    min_views: int,
    min_duration_sec: int,
    max_duration_sec: int,
    title: str = '',
    channel_title: str = '',
    title_blocklist: str = '',
    channel_allowlist: str = '',
    channel_blocklist: str = '',
) -> bool:
    if view_count < min_views:
        return False
    if duration_sec < min_duration_sec:
        return False
    if duration_sec > max_duration_sec:
        return False
    title_low = title.lower()
    channel_low = channel_title.lower()
    if any(term in title_low for term in _csv_values(title_blocklist)):
        return False
    if any(term in channel_low for term in _csv_values(channel_blocklist)):
        return False
    allowlist = _csv_values(channel_allowlist)
    if allowlist and not any(term in channel_low for term in allowlist):
        return False
    return True


def compute_score_details(
    *,
    view_count: int,
    published_at: str,
    duration_sec: int = 0,
    title: str = '',
    keyword: str = '',
    channel_title: str = '',
) -> dict[str, float]:
    """Return explainable score components from fields available in search results."""
    views_term = math.log10(max(10, view_count))

    freshness_term = 0.0
    try:
        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00')).astimezone(timezone.utc)
        age_hours = max(1.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
        freshness_term = 24.0 / age_hours
    except Exception:
        freshness_term = 0.0

    duration_term = 0.0
    if duration_sec > 0:
        if 120 <= duration_sec <= 900:
            duration_term = 0.6
        elif 60 <= duration_sec <= 1800:
            duration_term = 0.2

    title_low = title.lower()
    keyword_low = keyword.lower()
    keyword_term = 0.5 if keyword_low and keyword_low in title_low else 0.0
    channel_term = 0.2 if channel_title.strip() else 0.0

    total = views_term + freshness_term + duration_term + keyword_term + channel_term
    return {
        'score_total': round(total, 6),
        'score_views': round(views_term, 6),
        'score_freshness': round(freshness_term, 6),
        'score_duration': round(duration_term, 6),
        'score_channel': round(channel_term, 6),
        'score_keyword': round(keyword_term, 6),
        'penalty_title': 0.0,
        'penalty_duplicate': 0.0,
    }


def compute_hot_score(view_count: int, published_at: str) -> float:
    """Compatibility wrapper for callers that only need the final score."""
    return compute_score_details(view_count=view_count, published_at=published_at)['score_total']


def dedupe_and_sort(candidates: list[VideoCandidate], top_n: int) -> list[VideoCandidate]:
    latest: dict[str, VideoCandidate] = {}
    for item in candidates:
        prev = latest.get(item.video_id)
        if prev is None or item.score > prev.score:
            latest[item.video_id] = item
    ordered = sorted(latest.values(), key=lambda x: x.score, reverse=True)
    return ordered[: max(1, top_n)]
