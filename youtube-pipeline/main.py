from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.config import load_config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.downloader import download_video_assets
from app.logger import setup_logger
from app.pipeline import run_download_publish
from app.publisher import publish_to_bilibili
from app.youtube_api import parse_video_id


logger = logging.getLogger("youtube-pipeline")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local YouTube download, merge, and Bilibili publish pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download and merge one YouTube video.")
    download_parser.add_argument("url", help="YouTube video URL")

    subparsers.add_parser("init-db", help="Initialize the SQLite database.")

    add_url_parser = subparsers.add_parser("add-url", help="Add one YouTube URL to the local queue.")
    add_url_parser.add_argument("url", help="YouTube video URL")
    add_url_parser.add_argument("--status", default="selected", help="Initial video status, default: selected")

    list_parser = subparsers.add_parser("list", help="List videos in the local database.")
    list_parser.add_argument("--status", help="Filter by video status")
    list_parser.add_argument("--limit", type=int, default=50, help="Maximum rows")
    list_parser.add_argument("--offset", type=int, default=0, help="Offset")

    show_parser = subparsers.add_parser("show", help="Show one video record.")
    show_parser.add_argument("video_id", help="YouTube video id or URL")

    events_parser = subparsers.add_parser("events", help="Show recent events.")
    events_parser.add_argument("video_id", nargs="?", help="Optional YouTube video id or URL")
    events_parser.add_argument("--limit", type=int, default=50, help="Maximum rows")

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
        if args.command == "init-db":
            with connect(config.db_path) as conn:
                init_schema(conn)
            result = {"db_path": str(config.db_path), "initialized": True}
        elif args.command == "add-url":
            video_id = parse_video_id(args.url)
            with connect(config.db_path) as conn:
                init_schema(conn)
                repo = Repository(conn)
                video = repo.upsert_video(video_id=video_id, source_url=args.url, status=args.status)
                repo.create_job("download", video_id=video_id, payload={"url": args.url})
                conn.commit()
            result = {"video": video}
        elif args.command == "list":
            with connect(config.db_path) as conn:
                init_schema(conn)
                repo = Repository(conn)
                result = {"videos": repo.list_videos(status=args.status, limit=args.limit, offset=args.offset)}
        elif args.command == "show":
            video_id = parse_video_id(args.video_id)
            with connect(config.db_path) as conn:
                init_schema(conn)
                repo = Repository(conn)
                video = repo.get_video(video_id)
            if video is None:
                raise RuntimeError(f"Video not found: {video_id}")
            result = {"video": video}
        elif args.command == "events":
            video_id = parse_video_id(args.video_id) if args.video_id else None
            with connect(config.db_path) as conn:
                init_schema(conn)
                repo = Repository(conn)
                result = {"events": repo.list_events(video_id=video_id, limit=args.limit)}
        elif args.command == "download":
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
