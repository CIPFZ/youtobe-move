from __future__ import annotations

import json
from typing import Any

from app.config import Config
from app.discovery.models import DiscoverySource, VideoCandidate, candidate_from_youtube_item
from app.youtube_api import get_channel_id_by_handle, get_channel_uploads, get_trending_videos, search_videos


def load_discovery_sources(config: Config, source_type: str | None = None) -> list[DiscoverySource]:
    try:
        raw_sources = json.loads(config.discovery_sources_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"DISCOVERY_SOURCES_JSON is invalid JSON: {exc}") from exc
    if not isinstance(raw_sources, list):
        raise ValueError("DISCOVERY_SOURCES_JSON must be a JSON array")

    sources: list[DiscoverySource] = []
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict):
            raise ValueError(f"Discovery source #{index} must be an object")
        current_type = str(item.get("type") or "").strip()
        if not current_type:
            raise ValueError(f"Discovery source #{index} is missing type")
        if source_type and current_type != source_type:
            continue
        name = str(item.get("name") or f"{current_type}:{index}")
        sources.append(DiscoverySource(type=current_type, name=name, params=item))
    return sources


def _max_results(source: DiscoverySource, config: Config) -> int:
    value = source.params.get("max_results", config.discovery_max_results_per_source)
    return max(1, min(int(value), 50))


def fetch_candidates_for_source(source: DiscoverySource, config: Config) -> list[VideoCandidate]:
    if source.type == "search":
        keyword = str(source.params.get("keyword") or source.params.get("q") or "").strip()
        if not keyword:
            raise ValueError(f"search source is missing keyword: {source.name}")
        items = search_videos(
            config,
            keyword=keyword,
            max_results=_max_results(source, config),
            order=source.params.get("order"),
            channel_id=source.params.get("channel_id"),
            published_after=source.params.get("published_after"),
            region_code=source.params.get("region_code"),
            relevance_language=source.params.get("relevance_language"),
            video_category_id=source.params.get("video_category_id"),
        )
        source_query = keyword
    elif source.type == "trending":
        region_code = str(source.params.get("region_code") or "US").strip()
        video_category_id = source.params.get("video_category_id")
        items = get_trending_videos(
            config,
            region_code=region_code,
            max_results=_max_results(source, config),
            video_category_id=str(video_category_id) if video_category_id else None,
        )
        source_query = f"region={region_code},category={video_category_id or ''}"
    elif source.type == "channel_uploads":
        channel_id = str(source.params.get("channel_id") or "").strip()
        handle = str(source.params.get("handle") or "").strip()
        if not channel_id and handle:
            channel_id = get_channel_id_by_handle(config, handle)
        if not channel_id:
            raise ValueError(f"channel_uploads source is missing channel_id or handle: {source.name}")
        items = get_channel_uploads(config, channel_id=channel_id, max_results=_max_results(source, config))
        source_query = handle or channel_id
    else:
        raise ValueError(f"Unsupported discovery source type: {source.type}")

    candidates: list[VideoCandidate] = []
    for item in items:
        candidate = candidate_from_youtube_item(item, source, source_query)
        if candidate:
            candidates.append(candidate)
    return candidates


def fetch_candidates(config: Config, source_type: str | None = None) -> list[VideoCandidate]:
    candidates: list[VideoCandidate] = []
    for source in load_discovery_sources(config, source_type=source_type):
        candidates.extend(fetch_candidates_for_source(source, config))
    return candidates
