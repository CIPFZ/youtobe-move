from __future__ import annotations

import logging
import os
from pathlib import Path

from app.discovery.models import VideoCandidate
from app.discovery.scoring import dedupe_and_sort
from app.discovery.youtube_discovery import discover_candidates
from app.settings import settings

logger = logging.getLogger(__name__)


def _csv_values(s: str) -> list[str]:
    return [x.strip() for x in s.split(',') if x.strip()]


# ── Topic registry: maps topic type to (keywords_setting_attr, languages_setting_attr) ──
TOPIC_REGISTRY: dict[str, tuple[str, str]] = {
    'ai':      ('discovery_topic_ai_keywords',      'discovery_topic_ai_languages'),
    'tech':    ('discovery_topic_tech_keywords',     'discovery_topic_tech_languages'),
    'digital': ('discovery_topic_digital_keywords',  'discovery_topic_digital_languages'),
    'pets':    ('discovery_topic_pets_keywords',     'discovery_topic_pets_languages'),
    'beauty':  ('discovery_topic_beauty_keywords',   'discovery_topic_beauty_languages'),
    'funny':   ('discovery_topic_funny_keywords',    'discovery_topic_funny_languages'),
}


def discovery_keywords() -> list[tuple[str, str, list[str]]]:
    """Return [(keyword, category, allowed_languages), ...] for active topics.

    Each entry: keyword, its category label, and a list of language prefixes
    that are allowed for this category (empty = allow all).
    """
    selected_types = [x.lower() for x in _csv_values(settings.discovery_topic_types)]
    merged: list[tuple[str, str, list[str]]] = []
    seen: set[str] = set()

    for topic in selected_types:
        reg = TOPIC_REGISTRY.get(topic)
        if reg is None:
            logger.warning('Unknown discovery topic type: %s', topic)
            continue
        keywords_attr, langs_attr = reg
        keywords_raw = str(getattr(settings, keywords_attr, '') or '')
        langs_raw = str(getattr(settings, langs_attr, '') or '')

        allowed_langs = [x.strip().lower() for x in langs_raw.split(',') if x.strip()]

        for kw in _csv_values(keywords_raw):
            low = kw.lower()
            if low in seen:
                continue
            seen.add(low)
            merged.append((kw, topic, allowed_langs))

    # extra keywords (no category affiliation)
    for kw in _csv_values(settings.discovery_keywords):
        low = kw.lower()
        if low in seen:
            continue
        seen.add(low)
        merged.append((kw, '', []))

    return merged


def _load_api_key_runtime() -> str:
    # 1) runtime env has highest priority
    env_key = os.getenv('YOUTUBE_API_KEY', '').strip()
    if env_key:
        return env_key

    # 2) value loaded at startup via pydantic settings
    cfg_key = settings.youtube_api_key.strip()
    if cfg_key:
        return cfg_key

    # 3) fallback: read .env
    env_file = Path('.env')
    if not env_file.exists():
        return ''
    try:
        for ln in env_file.read_text(encoding='utf-8').splitlines():
            line = ln.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            if k.strip() == 'YOUTUBE_API_KEY':
                return v.strip().strip('"').strip("'")
    except Exception:
        return ''
    return ''


def run_discovery_once(*, top_n: int = 0, days_back: int = 0) -> tuple[list[VideoCandidate], list[VideoCandidate]]:
    api_key = _load_api_key_runtime()
    if not api_key:
        raise RuntimeError('YOUTUBE_API_KEY is required for daily discovery')

    kw_triples = discovery_keywords()
    if not kw_triples:
        raise RuntimeError('DISCOVERY_TOPIC_TYPES or keywords is empty')

    top = top_n if top_n > 0 else settings.discovery_top_n
    days = days_back if days_back > 0 else settings.discovery_days_back

    # build lookup: keyword -> (category, allowed_languages)
    kw_meta: dict[str, tuple[str, list[str]]] = {}
    for kw, cat, langs in kw_triples:
        kw_meta[kw.strip().lower()] = (cat, langs)

    keywords = [kw for kw, _, _ in kw_triples]

    raw = discover_candidates(
        api_key=api_key,
        keywords=keywords,
        days_back=days,
        max_results_per_keyword=settings.discovery_max_results_per_keyword,
        min_views=settings.discovery_min_views,
        min_comments=settings.discovery_min_comments,
        min_duration_sec=settings.discovery_min_duration_sec,
        max_duration_sec=settings.discovery_max_duration_sec,
        kw_meta=kw_meta,
    )
    selected = dedupe_and_sort(raw, top_n=top)
    logger.info('Daily discovery selected=%d (raw=%d)', len(selected), len(raw))
    return raw, selected
