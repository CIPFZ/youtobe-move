from __future__ import annotations

from app.discovery.models import VideoCandidate
from app.discovery.providers.base import SearchKeyword
from app.discovery.providers.ytdlp_search import YtdlpSearchProvider, _parse_upload_date


def discover_candidates(
    *,
    keywords: list[SearchKeyword],
    max_results_per_keyword: int,
    min_views: int,
    min_duration_sec: int,
    max_duration_sec: int,
) -> list[VideoCandidate]:
    """Compatibility wrapper for the legacy discovery import path."""
    return YtdlpSearchProvider().search(
        keywords=keywords,
        max_results_per_keyword=max_results_per_keyword,
        min_views=min_views,
        min_duration_sec=min_duration_sec,
        max_duration_sec=max_duration_sec,
    )
