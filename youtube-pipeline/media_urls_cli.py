from __future__ import annotations

import argparse
import json
import logging

from app.config import load_config
from app.logger import setup_logger
from app.media_urls import get_media_urls


logger = logging.getLogger("youtube-pipeline")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve direct video/audio media URLs with yt-dlp.")
    parser.add_argument("url", help="YouTube video URL")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config()
    setup_logger(config.log_level, config.log_file)

    try:
        result = get_media_urls(args.url, config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        logger.exception("Resolve media URLs failed: url=%s", args.url)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
