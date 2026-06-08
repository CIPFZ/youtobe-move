#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STAGES = [
    ('tests.test_downloader_stage', []),
    ('tests.test_ffmpeg_stage', []),
    ('tests.test_subtitles_stage', []),
    ('tests.test_merge_ass_audio_video', []),
    ('tests.test_transcriber_stage', []),
    ('tests.test_translator_stage', []),
    ('tests.test_dubbing_pipeline_stage', []),
    ('tests.test_pipeline_e2e', []),
]


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    for mod, extra_args in STAGES:
        cmd = [sys.executable, '-m', mod, *extra_args]
        print(f'===== running {mod} =====')
        rc = subprocess.call(cmd, cwd=repo_root)
        if rc != 0:
            print(f'[FAIL] {mod} rc={rc}')
            return rc
    print('all stage checks passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
