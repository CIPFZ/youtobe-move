from __future__ import annotations

import argparse
import json

from app.config import load_config
from app.logger import setup_logger
from app.youtube_api import get_video_meta, search_videos


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Query YouTube Data API metadata and search results.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    video_parser = subparsers.add_parser("video", help="Get metadata for one YouTube video URL or id.")
    video_parser.add_argument("url", help="YouTube video URL or video id")

    search_parser = subparsers.add_parser("search", help="Search videos and return full metadata.")
    search_parser.add_argument("keyword", help="Search keyword")
    search_parser.add_argument("--max-results", type=int, default=5, help="Max search results, default: 5")

    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config()
    setup_logger(config.log_level, config.log_file)

    if args.command == "video":
        result = get_video_meta(config, args.url)
    elif args.command == "search":
        result = search_videos(config, args.keyword, args.max_results)
    else:
        raise RuntimeError(f"Unknown command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
