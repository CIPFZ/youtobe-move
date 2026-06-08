from __future__ import annotations

from pathlib import Path

from app.subtitles import Segment


def _srt_time_to_sec(s: str) -> float:
    hhmmss, ms = s.split(',')
    h, m, sec = hhmmss.split(':')
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0


def read_srt(path: Path) -> list[Segment]:
    content = path.read_text(encoding='utf-8').strip()
    if not content:
        return []

    blocks = [b.strip() for b in content.split('\n\n') if b.strip()]
    out: list[Segment] = []
    for block in blocks:
        lines = [ln.rstrip('\n') for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        ts = lines[1]
        if ' --> ' not in ts:
            continue
        start_s, end_s = ts.split(' --> ', 1)
        text = '\n'.join(lines[2:]).strip()
        out.append(Segment(start=_srt_time_to_sec(start_s.strip()), end=_srt_time_to_sec(end_s.strip()), text=text))
    return out

