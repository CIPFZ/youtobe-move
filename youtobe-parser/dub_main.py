#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from app.dubbing_pipeline import DubbingPipeline
from app.logging_utils import setup_logging
from app.settings import settings


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='独立中文配音流程（输入已存在的 mp4/m4a/srt/ass）')
    p.add_argument('--video', type=Path, required=True, help='Input MP4 video path')
    p.add_argument('--audio', type=Path, required=True, help='Input M4A (or audio) path')
    p.add_argument('--srt', type=Path, required=True, help='Input SRT path')
    p.add_argument('--ass', type=Path, required=True, help='Input ASS path')
    p.add_argument('--stem', type=str, default='', help='Output stem; default uses video stem')
    return p.parse_args()


def main() -> None:
    args = parse_args()
    setup_logging(settings.log_level, settings.log_file)
    logger = logging.getLogger(__name__)

    output = DubbingPipeline().run(
        video_path=args.video.resolve(),
        audio_path=args.audio.resolve(),
        srt_path=args.srt.resolve(),
        ass_path=args.ass.resolve(),
        stem=args.stem.strip() or None,
    )
    logger.info('Dubbing pipeline completed. output=%s', output)
    print(f'完成: {output}')


if __name__ == '__main__':
    main()

