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


def filter_candidate(candidate: VideoCandidate, repo: Repository, config: Config) -> FilterResult:
    if repo.get_video(candidate.video_id):
        return FilterResult(False, "duplicate_video_id")

    if config.discovery_min_duration_seconds and candidate.duration is not None:
        if candidate.duration < config.discovery_min_duration_seconds:
            return FilterResult(False, "duration_too_short")

    if config.discovery_max_duration_seconds and candidate.duration is not None:
        if candidate.duration > config.discovery_max_duration_seconds:
            return FilterResult(False, "duration_too_long")

    if config.discovery_min_view_count and candidate.view_count is not None:
        if candidate.view_count < config.discovery_min_view_count:
            return FilterResult(False, "view_count_too_low")

    title = candidate.title.lower()
    for blocked in parse_blocklist(config.discovery_title_blocklist):
        if blocked in title:
            return FilterResult(False, f"title_blocked:{blocked}")

    channel_tokens = {candidate.channel_id.lower(), candidate.channel.lower()}
    allow_channels = [item.lower() for item in parse_csv(config.discovery_channel_allowlist)]
    if allow_channels and not any(item in channel_tokens for item in allow_channels):
        return FilterResult(False, "channel_not_allowed")

    for blocked in [item.lower() for item in parse_csv(config.discovery_channel_blocklist)]:
        if blocked in channel_tokens:
            return FilterResult(False, f"channel_blocked:{blocked}")

    allow_categories = parse_csv(config.discovery_category_allowlist)
    if allow_categories and candidate.category not in allow_categories:
        return FilterResult(False, "category_not_allowed")

    for blocked in parse_csv(config.discovery_category_blocklist):
        if candidate.category == blocked:
            return FilterResult(False, f"category_blocked:{blocked}")

    return FilterResult(True)
