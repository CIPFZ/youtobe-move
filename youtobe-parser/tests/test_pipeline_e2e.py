#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from app.pipeline import Pipeline
from app.settings import settings


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Real pipeline e2e test (no mock).')
    p.add_argument('--url', type=str, default='', help='Source media URL. If empty, read PIPELINE_TEST_URL or SOURCE_URL.')
    p.add_argument('--require-url', action='store_true', help='Fail if URL is not provided.')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    url = args.url.strip() or os.getenv('PIPELINE_TEST_URL', '').strip() or settings.source_url.strip()
    if not url:
        if args.require_url:
            raise RuntimeError('Pipeline URL is required: pass --url or set PIPELINE_TEST_URL/SOURCE_URL')
        print('[SKIP] pipeline e2e skipped: URL not set')
        return 0

    outputs = Pipeline().run(url)
    output = outputs.bilingual_video
    if not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError('pipeline bilingual output not generated')
    if settings.pipeline_enable_dubbing:
        if outputs.dubbed_video is None or not outputs.dubbed_video.exists() or outputs.dubbed_video.stat().st_size <= 0:
            raise RuntimeError('pipeline dubbed output not generated')

    metadata_dir = settings.work_dir.resolve() / settings.metadata_dirname
    files = list(metadata_dir.glob('*.video_info.json'))
    if not files:
        raise RuntimeError('metadata json not generated')

    print(f'[OK] pipeline e2e completed: bilingual={output} dubbed={outputs.dubbed_video} metadata_count={len(files)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
