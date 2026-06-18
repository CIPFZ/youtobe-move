from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.config import load_config
from app.downloader import download_video_assets
from app.logger import setup_logger
from app.pipeline import run_download_publish
from app.publisher import publish_to_bilibili


logger = logging.getLogger("youtube-pipeline")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local YouTube download, merge, and Bilibili publish pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download and merge one YouTube video.")
    download_parser.add_argument("url", help="YouTube video URL")

    publish_parser = subparsers.add_parser("publish", help="Publish an existing downloaded video directory to Bilibili.")
    publish_parser.add_argument("data_dir", type=Path, help="Directory containing meta.json and <id>_merge.mp4")
    publish_parser.add_argument("--tid", type=int, help="Bilibili category id. Defaults to BILIBILI_TID.")
    publish_parser.add_argument("--dry-run", action="store_true", help="Generate publish payload without uploading")

    run_parser = subparsers.add_parser("run", help="Download, merge, generate description, and publish.")
    run_parser.add_argument("url", help="YouTube video URL")
    run_parser.add_argument("--tid", type=int, help="Bilibili category id. Defaults to BILIBILI_TID.")
    run_parser.add_argument("--dry-run-publish", action="store_true", help="Download but do not upload to Bilibili")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config = load_config()
    setup_logger(config.log_level, config.log_file)

    try:
        if args.command == "download":
            logger.info("Download job started: url=%s", args.url)
            result = download_video_assets(args.url, config)
            logger.info("Download job completed: video_id=%s output_dir=%s", result["video_id"], result["output_dir"])
        elif args.command == "publish":
            logger.info("Publish job started: data_dir=%s", args.data_dir)
            result = publish_to_bilibili(args.data_dir, config, tid=args.tid, dry_run=args.dry_run)
            logger.info("Publish job completed: video_file=%s", result["video_file"])
        elif args.command == "run":
            logger.info("Pipeline job started: url=%s", args.url)
            result = run_download_publish(args.url, config, tid=args.tid, dry_run_publish=args.dry_run_publish)
            logger.info("Pipeline job completed: video_id=%s", result["download"]["video_id"])
        else:
            raise RuntimeError(f"Unknown command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception:
        logger.exception("Pipeline command failed: command=%s", args.command)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
