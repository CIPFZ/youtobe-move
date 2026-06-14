from __future__ import annotations

from app.discovery.models import VideoCandidate
from app.discovery.providers.base import SearchKeyword, UnsupportedProviderError


class YoutubeApiProvider:
    name = "youtube_api"

    def search(
        self,
        *,
        keywords: list[SearchKeyword],
        max_results_per_keyword: int,
        min_views: int,
        min_duration_sec: int,
        max_duration_sec: int,
    ) -> list[VideoCandidate]:
        raise UnsupportedProviderError(
            "DISCOVERY_PROVIDER=youtube_api is not implemented yet. Use DISCOVERY_PROVIDER=ytdlp."
        )

