from __future__ import annotations

import argparse
import json
import logging

from app.config import load_config
from app.downloader import download_video_assets
from app.logger import setup_logger


logger = logging.getLogger("hk-server")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download one YouTube video's metadata, best video stream, best audio stream, and poster.",
    )
    parser.add_argument("url", help="YouTube video URL")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config()
    setup_logger(config.log_level, config.log_file)

    try:
        logger.info("Download job started: url=%s", args.url)
        result = download_video_assets(args.url, config)
        logger.info("Download job completed: video_id=%s output_dir=%s", result["video_id"], result["output_dir"])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        logger.exception("Download job failed: url=%s", args.url)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
