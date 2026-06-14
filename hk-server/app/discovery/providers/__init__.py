from __future__ import annotations

from app.discovery.providers.base import DiscoveryProvider, SearchKeyword, UnsupportedProviderError
from app.discovery.providers.ytdlp_search import YtdlpSearchProvider
from app.discovery.providers.youtube_api import YoutubeApiProvider


def get_provider(name: str) -> DiscoveryProvider:
    provider_name = (name or "ytdlp").strip().lower().replace("-", "_")
    if provider_name in {"ytdlp", "yt_dlp", "yt_dlp_search"}:
        return YtdlpSearchProvider()
    if provider_name in {"youtube_api", "youtube"}:
        return YoutubeApiProvider()
    raise UnsupportedProviderError(f"Unsupported discovery provider: {name}")

