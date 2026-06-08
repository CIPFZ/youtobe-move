from __future__ import annotations

import math
from datetime import datetime, timezone

from app.discovery.models import VideoCandidate


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def _language_allowed(language_hint: str, allowed_languages: list[str]) -> bool:
    """Return True if *language_hint* matches any prefix in *allowed_languages*.

    An empty *allowed_languages* list means ALL languages are allowed.
    """
    if not allowed_languages:
        return True
    lang = (language_hint or '').strip().lower()
    if not lang:
        return True  # unknown language: let it through rather than silently drop
    for prefix in allowed_languages:
        if lang.startswith(prefix.strip().lower()):
            return True
    return False


def should_keep_candidate(
    *,
    view_count: int,
    comment_count: int,
    duration_sec: int,
    language_hint: str,
    allowed_languages: list[str],
    min_views: int,
    min_comments: int,
    min_duration_sec: int,
    max_duration_sec: int,
) -> bool:
    if not _language_allowed(language_hint, allowed_languages):
        return False
    if view_count < min_views:
        return False
    if comment_count < min_comments:
        return False
    if duration_sec < min_duration_sec:
        return False
    if duration_sec > max_duration_sec:
        return False
    return True


def compute_hot_score(view_count: int, comment_count: int, published_at: str) -> float:
    """Simple ranking score balancing views/comments/freshness."""
    views_term = math.log10(max(10, view_count))
    comments_term = math.log10(max(5, comment_count)) * 1.3

    freshness_term = 0.0
    try:
        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00')).astimezone(timezone.utc)
        age_hours = max(1.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
        freshness_term = 24.0 / age_hours
    except Exception:
        freshness_term = 0.0

    return round(views_term + comments_term + freshness_term, 6)


def dedupe_and_sort(candidates: list[VideoCandidate], top_n: int) -> list[VideoCandidate]:
    latest: dict[str, VideoCandidate] = {}
    for item in candidates:
        prev = latest.get(item.video_id)
        if prev is None or item.score > prev.score:
            latest[item.video_id] = item
    ordered = sorted(latest.values(), key=lambda x: x.score, reverse=True)
    return ordered[: max(1, top_n)]
