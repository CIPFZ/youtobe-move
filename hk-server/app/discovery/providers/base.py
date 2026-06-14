from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.discovery.models import VideoCandidate


@dataclass(frozen=True)
class SearchKeyword:
    keyword: str
    category: str


class UnsupportedProviderError(RuntimeError):
    pass


class DiscoveryProvider(Protocol):
    name: str

    def search(
        self,
        *,
        keywords: list[SearchKeyword],
        max_results_per_keyword: int,
        min_views: int,
        min_duration_sec: int,
        max_duration_sec: int,
    ) -> list[VideoCandidate]:
        ...

