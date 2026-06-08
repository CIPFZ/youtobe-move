from __future__ import annotations

from dataclasses import dataclass
import re

from app.settings import settings
from app.subtitles import Segment


@dataclass
class DubbingSegment:
    id: int
    start: float
    end: float
    source_text: str
    translated_text: str = ''

    @property
    def duration(self) -> float:
        return max(0.01, self.end - self.start)


def _collapse_repeated_clauses(text: str) -> str:
    cleaned = ' '.join(text.split())
    if not cleaned:
        return ''
    parts = re.split(r'([,.;:!?])', cleaned)
    clauses: list[str] = []
    i = 0
    while i < len(parts):
        body = (parts[i] or '').strip()
        punct = (parts[i + 1] or '') if i + 1 < len(parts) else ''
        clause = f'{body}{punct}'.strip()
        if clause:
            clauses.append(clause)
        i += 2

    deduped: list[str] = []
    prev_norm = ''
    for clause in clauses:
        norm = ' '.join(clause.lower().split())
        if norm == prev_norm:
            continue
        deduped.append(clause)
        prev_norm = norm
    return ' '.join(deduped)


def build_semantic_segments(segments: list[Segment]) -> list[DubbingSegment]:
    if not segments:
        return []

    out: list[DubbingSegment] = []
    gap_limit = float(settings.dubbing_segment_gap_sec)
    max_duration = float(settings.dubbing_max_segment_duration_sec)
    pending: list[Segment] = [segments[0]]

    def flush() -> None:
        if not pending:
            return
        i = len(out) + 1
        text = ' '.join(s.text.strip().replace('\n', ' ') for s in pending if s.text.strip())
        text = _collapse_repeated_clauses(text)
        out.append(DubbingSegment(id=i, start=pending[0].start, end=pending[-1].end, source_text=text))
        pending.clear()

    for seg in segments[1:]:
        cur = pending[-1]
        gap = max(0.0, seg.start - cur.end)
        new_duration = seg.end - pending[0].start
        if gap <= gap_limit and new_duration <= max_duration:
            pending.append(seg)
        else:
            flush()
            pending.append(seg)
    flush()
    return out


def estimate_chars_per_sec(text: str, duration: float) -> float:
    plain = ''.join(ch for ch in text if not ch.isspace())
    if duration <= 0:
        return float('inf')
    return len(plain) / duration
