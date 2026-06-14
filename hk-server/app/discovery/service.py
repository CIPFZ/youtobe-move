from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from app.discovery.models import VideoCandidate
from app.discovery.providers import get_provider
from app.discovery.providers.base import SearchKeyword
from app.discovery.scoring import dedupe_and_sort
from app.settings import settings

logger = logging.getLogger(__name__)


def _csv_values(s: str) -> list[str]:
    return [x.strip() for x in s.split(',') if x.strip()]


TOPIC_REGISTRY: dict[str, str] = {
    'ai': 'discovery_topic_ai_keywords',
    'tech': 'discovery_topic_tech_keywords',
    'digital': 'discovery_topic_digital_keywords',
    'pets': 'discovery_topic_pets_keywords',
    'beauty': 'discovery_topic_beauty_keywords',
    'funny': 'discovery_topic_funny_keywords',
}


def discovery_keywords() -> list[SearchKeyword]:
    selected_types = [x.lower() for x in _csv_values(settings.discovery_topic_types)]
    merged: list[SearchKeyword] = []
    seen: set[str] = set()

    for topic in selected_types:
        keywords_attr = TOPIC_REGISTRY.get(topic)
        if keywords_attr is None:
            logger.warning('Unknown discovery topic type: %s', topic)
            continue
        keywords_raw = str(getattr(settings, keywords_attr, '') or '')

        for kw in _csv_values(keywords_raw):
            low = kw.lower()
            if low in seen:
                continue
            seen.add(low)
            merged.append(SearchKeyword(keyword=kw, category=topic))

    for kw in _csv_values(settings.discovery_keywords):
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        merged.append(SearchKeyword(keyword=kw, category=''))

    return merged


def run_discovery_once(*, top_n: int = 0) -> tuple[list[VideoCandidate], list[VideoCandidate]]:
    keywords = discovery_keywords()
    if not keywords:
        raise RuntimeError('DISCOVERY_TOPIC_TYPES or DISCOVERY_KEYWORDS is empty')

    top = top_n if top_n > 0 else settings.discovery_top_n
    provider = get_provider(settings.discovery_provider)

    raw = provider.search(
        keywords=keywords,
        max_results_per_keyword=settings.discovery_max_results_per_keyword,
        min_views=settings.discovery_min_views,
        min_duration_sec=settings.discovery_min_duration_sec,
        max_duration_sec=settings.discovery_max_duration_sec,
    )
    selected = dedupe_and_sort(raw, top_n=top)
    logger.info(
        'Daily discovery selected=%d (raw=%d provider=%s)',
        len(selected), len(raw), provider.name,
    )
    return raw, selected


def discovery_preview(*, top_n: int = 0) -> dict[str, Any]:
    raw, selected = run_discovery_once(top_n=top_n)
    return {
        "provider": get_provider(settings.discovery_provider).name,
        "raw_count": len(raw),
        "selected_count": len(selected),
        "items": [asdict(item) for item in selected],
        "raw_items": [asdict(item) for item in raw],
    }
