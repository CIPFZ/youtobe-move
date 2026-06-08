#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from app.subtitles import Segment, sec_to_ass, sec_to_srt, write_ass, write_srt


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Real subtitles format/write stage test (no mock).')
    p.add_argument('--work-dir', type=Path, help='Work directory. If omitted, use a temporary directory.')
    p.add_argument('--text', type=str, default='hello\nworld', help='Subtitle text content to write.')
    return p.parse_args()


def _run_once(base: Path, text: str) -> tuple[Path, Path]:
    base.mkdir(parents=True, exist_ok=True)
    srt = base / 'a.srt'
    ass = base / 'a.ass'
    segments = [Segment(0.0, 1.2, text)]

    if sec_to_srt(3661.257) != '01:01:01,257':
        raise RuntimeError('sec_to_srt format mismatch')
    if sec_to_ass(3661.257) != '1:01:01.25':
        raise RuntimeError('sec_to_ass format mismatch')

    write_srt(segments, srt)
    write_ass(segments, ass)

    srt_text = srt.read_text(encoding='utf-8')
    ass_text = ass.read_text(encoding='utf-8')

    if '00:00:00,000 --> 00:00:01,199' not in srt_text:
        raise RuntimeError('srt timestamp mismatch')
    if text not in srt_text:
        raise RuntimeError('srt content mismatch')
    if '[Events]' not in ass_text or r'hello\Nworld' not in ass_text:
        raise RuntimeError('ass content mismatch')
    return srt, ass


def main() -> int:
    args = parse_args()
    if args.work_dir:
        srt, ass = _run_once(args.work_dir.resolve(), args.text)
        print(f'[OK] subtitles stage completed: {srt} / {ass}')
        return 0

    with tempfile.TemporaryDirectory(prefix='subtitles-stage-') as td:
        srt, ass = _run_once(Path(td), args.text)
        print(f'[OK] subtitles stage completed: {srt} / {ass}')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
