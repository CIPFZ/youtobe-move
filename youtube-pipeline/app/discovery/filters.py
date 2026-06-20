from __future__ import annotations

from dataclasses import dataclass

from app.config import Config
from app.core.repository import Repository
from app.discovery.models import VideoCandidate


@dataclass(frozen=True)
class FilterResult:
    accepted: bool
    reason: str = ""


def parse_blocklist(raw: str) -> list[str]:
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _source_value(candidate: VideoCandidate, key: str, fallback):
    value = candidate.source_params.get(key)
    if value in (None, ""):
        return fallback
    return value


def _source_int(candidate: VideoCandidate, key: str, fallback: int) -> int:
    value = _source_value(candidate, key, fallback)
    return int(value or 0)


def _source_text(candidate: VideoCandidate, key: str, fallback: str) -> str:
    return str(_source_value(candidate, key, fallback) or "")


def filter_candidate(candidate: VideoCandidate, repo: Repository, config: Config) -> FilterResult:
    if repo.get_video(candidate.video_id):
        return FilterResult(False, "duplicate_video_id")

    min_duration = _source_int(candidate, "min_duration_seconds", config.discovery_min_duration_seconds)
    if min_duration and candidate.duration is not None:
        if candidate.duration < min_duration:
            return FilterResult(False, "duration_too_short")

    max_duration = _source_int(candidate, "max_duration_seconds", config.discovery_max_duration_seconds)
    if max_duration and candidate.duration is not None:
        if candidate.duration > max_duration:
            return FilterResult(False, "duration_too_long")

    min_view_count = _source_int(candidate, "min_view_count", config.discovery_min_view_count)
    if min_view_count and candidate.view_count is not None:
        if candidate.view_count < min_view_count:
            return FilterResult(False, "view_count_too_low")

    title = candidate.title.lower()
    for blocked in parse_blocklist(_source_text(candidate, "title_blocklist", config.discovery_title_blocklist)):
        if blocked in title:
            return FilterResult(False, f"title_blocked:{blocked}")

    channel_tokens = {candidate.channel_id.lower(), candidate.channel.lower()}
    allow_channels = [item.lower() for item in parse_csv(_source_text(candidate, "channel_allowlist", config.discovery_channel_allowlist))]
    if allow_channels and not any(item in channel_tokens for item in allow_channels):
        return FilterResult(False, "channel_not_allowed")

    for blocked in [item.lower() for item in parse_csv(_source_text(candidate, "channel_blocklist", config.discovery_channel_blocklist))]:
        if blocked in channel_tokens:
            return FilterResult(False, f"channel_blocked:{blocked}")

    allow_categories = parse_csv(_source_text(candidate, "category_allowlist", config.discovery_category_allowlist))
    if allow_categories and candidate.category not in allow_categories:
        return FilterResult(False, "category_not_allowed")

    for blocked in parse_csv(_source_text(candidate, "category_blocklist", config.discovery_category_blocklist)):
        if candidate.category == blocked:
            return FilterResult(False, f"category_blocked:{blocked}")

    return FilterResult(True)
