from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.ffmpeg_tools import ffmpeg_bin


_DURATION_RE = re.compile(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)')


def probe_media_duration(path: Path) -> float:
    proc = subprocess.run(
        [ffmpeg_bin(), '-i', str(path), '-f', 'null', '-'],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    text = proc.stderr or ''
    m = _DURATION_RE.search(text)
    if not m:
        raise RuntimeError(f'Cannot parse media duration from ffmpeg output: {path}')
    h = int(m.group(1))
    mm = int(m.group(2))
    sec = float(m.group(3))
    return h * 3600 + mm * 60 + sec

