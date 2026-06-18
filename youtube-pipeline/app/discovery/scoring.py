from __future__ import annotations

import math
from dataclasses import replace

from app.discovery.models import VideoCandidate


SOURCE_WEIGHTS = {
    "channel_uploads": 30.0,
    "trending": 20.0,
    "search": 10.0,
}


def score_candidate(candidate: VideoCandidate) -> float:
    score = SOURCE_WEIGHTS.get(candidate.source_type, 0.0)
    if candidate.view_count is not None and candidate.view_count > 0:
        score += min(math.log10(candidate.view_count), 9.0) * 10.0

    if candidate.duration is not None:
        if 60 <= candidate.duration <= 600:
            score += 15.0
        elif 30 <= candidate.duration <= 1200:
            score += 5.0

    return round(score, 3)


def sort_candidates(candidates: list[VideoCandidate]) -> list[VideoCandidate]:
    scored = [replace(candidate, score=score_candidate(candidate)) for candidate in candidates]
    return sorted(scored, key=lambda item: item.score, reverse=True)
