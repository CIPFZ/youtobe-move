#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from app.settings import settings
from app.subtitles import Segment
from app.translator import SubtitleTranslator


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Real translator functional test (no mock).')
    p.add_argument('--text', action='append', default=[], help='Input text line. Can be repeated.')
    p.add_argument('--require-key', action='store_true', help='Fail if OPENAI_API_KEY is not set.')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    api_key = settings.openai_api_key.strip() or os.getenv('OPENAI_API_KEY', '').strip()
    if not api_key:
        if args.require_key:
            raise RuntimeError('OPENAI_API_KEY is required for translator stage test')
        print('[SKIP] translator stage skipped: OPENAI_API_KEY not set')
        return 0

    texts = args.text or ['Hello world.', 'How are you?']
    samples = [Segment(float(i), float(i + 1), t) for i, t in enumerate(texts)]
    out = SubtitleTranslator().translate(samples)
    if len(out) != len(samples):
        raise RuntimeError('translator output length mismatch')
    if any(not x.text.strip() for x in out):
        raise RuntimeError('translator returned empty text')
    print(f'[OK] translator stage completed: lines={len(out)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
