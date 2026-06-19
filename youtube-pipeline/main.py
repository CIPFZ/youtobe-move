from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from app.config import load_config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.discovery import discover_videos
from app.download_service import download_next, download_video_from_db
from app.downloader import download_video_assets
from app.logger import setup_logger
from app.operations import pipeline_status, retry_video, skip_video
from app.pipeline import run_download_publish
from app.publish_service import describe_video, publish_next, publish_video, review_publish_draft
from app.publisher import publish_to_bilibili
from app.web import run_web_server
from app.worker import run_worker_loop, run_worker_once
from app.youtube_api import parse_video_id


logger = logging.getLogger("youtube-pipeline")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local YouTube download, merge, and Bilibili publish pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download_parser = subparsers.add_parser("download", help="Download and merge one queued YouTube video.")
    download_parser.add_argument("video_id", help="YouTube video id or URL already saved in the database")
    download_parser.add_argument("--force", action="store_true", help="Redownload even if merged output already exists")

    download_next_parser = subparsers.add_parser("download-next", help="Download the next pending/selected video.")
    download_next_parser.add_argument("--force", action="store_true", help="Redownload even if merged output already exists")

    direct_download_parser = subparsers.add_parser("download-url", help="Directly download one URL without DB state.")
    direct_download_parser.add_argument("url", help="YouTube video URL")

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

    status_parser = subparsers.add_parser("status", help="Show pipeline status summary.")
    status_parser.add_argument("--events-limit", type=int, default=20, help="Recent events to include")

    retry_parser = subparsers.add_parser("retry", help="Retry one failed video.")
    retry_parser.add_argument("video_id", help="YouTube video id or URL")
    retry_parser.add_argument("--job-type", choices=["download", "describe", "publish"], help="Override retry job type")

    skip_parser = subparsers.add_parser("skip", help="Skip one video.")
    skip_parser.add_argument("video_id", help="YouTube video id or URL")
    skip_parser.add_argument("--force", action="store_true", help="Skip even if the video is in an active status")

    discover_parser = subparsers.add_parser("discover", help="Discover YouTube videos from configured sources.")
    discover_parser.add_argument("--source", choices=["search", "trending", "channel_uploads"], help="Run only one source type")
    discover_parser.add_argument("--dry-run", action="store_true", help="Fetch and filter candidates without inserting")

    describe_parser = subparsers.add_parser("describe", help="Generate a Bilibili publish draft for one downloaded video.")
    describe_parser.add_argument("video_id", help="YouTube video id or URL")
    describe_parser.add_argument("--force", action="store_true", help="Regenerate the publish draft")

    review_parser = subparsers.add_parser("review", help="Review one Bilibili publish draft.")
    review_parser.add_argument("video_id", help="YouTube video id or URL")
    review_parser.add_argument("status", choices=["pending", "approved", "rejected"], help="Draft review status")
    review_parser.add_argument("--note", default="", help="Optional review note")

    publish_parser = subparsers.add_parser("publish", help="Publish one ready video to Bilibili.")
    publish_parser.add_argument("video_id", help="YouTube video id or URL")
    publish_parser.add_argument("--dry-run", action="store_true", help="Build publish payload without uploading")
    publish_parser.add_argument("--force", action="store_true", help="Allow publishing even if a published record exists")

    publish_next_parser = subparsers.add_parser("publish-next", help="Publish the next ready video to Bilibili.")
    publish_next_parser.add_argument("--dry-run", action="store_true", help="Build publish payload without uploading")
    publish_next_parser.add_argument("--force", action="store_true", help="Allow publishing even if a published record exists")

    worker_run_parser = subparsers.add_parser("worker-run", help="Run one worker cycle.")
    worker_run_parser.add_argument(
        "--enable-publish",
        action="store_true",
        default=None,
        help="Allow this run to execute publish jobs",
    )
    worker_run_parser.add_argument("--publish-dry-run", action="store_true", help="Use dry-run for publish jobs in this run")

    worker_parser = subparsers.add_parser("worker", help="Run the worker loop.")
    worker_parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    worker_parser.add_argument("--interval", type=int, help="Loop interval in seconds")
    worker_parser.add_argument(
        "--enable-publish",
        action="store_true",
        default=None,
        help="Allow worker to execute publish jobs",
    )
    worker_parser.add_argument("--publish-dry-run", action="store_true", help="Use dry-run for publish jobs")

    web_parser = subparsers.add_parser("web", help="Run the local Web management UI.")
    web_parser.add_argument("--host", help="Bind host. Defaults to WEB_HOST.")
    web_parser.add_argument("--port", type=int, help="Bind port. Defaults to WEB_PORT.")

    publish_dir_parser = subparsers.add_parser("publish-dir", help="Publish an existing downloaded directory to Bilibili.")
    publish_dir_parser.add_argument("data_dir", type=Path, help="Directory containing meta.json and <id>_merge.mp4")
    publish_dir_parser.add_argument("--tid", type=int, help="Bilibili category id. Defaults to BILIBILI_TID.")
    publish_dir_parser.add_argument("--dry-run", action="store_true", help="Generate publish payload without uploading")

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
                media_files = repo.get_media_files(video_id)
                latest_download_job = repo.get_latest_job(video_id, "download")
                latest_describe_job = repo.get_latest_job(video_id, "describe")
                latest_publish_job = repo.get_latest_job(video_id, "publish")
                publish_draft = repo.get_publish_draft(video_id, "bilibili")
                publish_records = repo.list_publish_records(video_id)
            if video is None:
                raise RuntimeError(f"Video not found: {video_id}")
            result = {
                "video": video,
                "media_files": media_files,
                "latest_download_job": latest_download_job,
                "latest_describe_job": latest_describe_job,
                "latest_publish_job": latest_publish_job,
                "publish_draft": publish_draft,
                "publish_records": publish_records,
            }
        elif args.command == "events":
            video_id = parse_video_id(args.video_id) if args.video_id else None
            with connect(config.db_path) as conn:
                init_schema(conn)
                repo = Repository(conn)
                result = {"events": repo.list_events(video_id=video_id, limit=args.limit)}
        elif args.command == "status":
            result = pipeline_status(config, events_limit=args.events_limit)
        elif args.command == "retry":
            video_id = parse_video_id(args.video_id)
            result = retry_video(video_id, config, job_type=args.job_type)
        elif args.command == "skip":
            video_id = parse_video_id(args.video_id)
            result = skip_video(video_id, config, force=args.force)
        elif args.command == "discover":
            logger.info("Discovery started: source=%s dry_run=%s", args.source, args.dry_run)
            result = discover_videos(config, source_type=args.source, dry_run=args.dry_run)
            logger.info("Discovery completed: inserted=%s accepted=%s", result["inserted_count"], result["accepted_count"])
        elif args.command == "download":
            video_id = parse_video_id(args.video_id)
            logger.info("Stateful download job started: video_id=%s force=%s", video_id, args.force)
            result = download_video_from_db(video_id, config, force=args.force)
            logger.info("Stateful download job completed: video_id=%s status=%s", video_id, result["status"])
        elif args.command == "download-next":
            logger.info("Stateful download-next started: force=%s", args.force)
            result = download_next(config, force=args.force)
            logger.info("Stateful download-next completed: status=%s", result["status"])
        elif args.command == "download-url":
            logger.info("Direct download job started: url=%s", args.url)
            result = download_video_assets(args.url, config)
            logger.info("Direct download job completed: video_id=%s output_dir=%s", result["video_id"], result["output_dir"])
        elif args.command == "describe":
            video_id = parse_video_id(args.video_id)
            logger.info("Describe job started: video_id=%s force=%s", video_id, args.force)
            result = describe_video(video_id, config, force=args.force)
            logger.info("Describe job completed: video_id=%s status=%s", video_id, result["status"])
        elif args.command == "review":
            video_id = parse_video_id(args.video_id)
            result = review_publish_draft(video_id, config, args.status, note=args.note)
        elif args.command == "publish":
            video_id = parse_video_id(args.video_id)
            logger.info(
                "Publish job started: video_id=%s dry_run=%s force=%s",
                video_id,
                args.dry_run,
                args.force,
            )
            result = publish_video(video_id, config, dry_run=args.dry_run, force=args.force)
            logger.info("Publish job completed: video_id=%s status=%s", video_id, result["status"])
        elif args.command == "publish-next":
            logger.info("Publish-next started: dry_run=%s force=%s", args.dry_run, args.force)
            result = publish_next(config, dry_run=args.dry_run, force=args.force)
            logger.info("Publish-next completed: status=%s", result["status"])
        elif args.command == "worker-run":
            logger.info("Worker-run started")
            result = run_worker_once(
                config,
                enable_publish=args.enable_publish,
                publish_dry_run=args.publish_dry_run if args.publish_dry_run else None,
            )
            logger.info("Worker-run completed: status=%s", result["status"])
        elif args.command == "worker":
            logger.info("Worker loop started: once=%s interval=%s", args.once, args.interval)
            result = run_worker_loop(
                config,
                interval_seconds=args.interval,
                enable_publish=args.enable_publish,
                publish_dry_run=args.publish_dry_run if args.publish_dry_run else None,
                max_runs=1 if args.once else None,
            )
            logger.info("Worker loop stopped: status=%s", result["status"])
        elif args.command == "web":
            run_web_server(config, host=args.host, port=args.port)
            return 0
        elif args.command == "publish-dir":
            logger.info("Publish-dir job started: data_dir=%s", args.data_dir)
            result = publish_to_bilibili(args.data_dir, config, tid=args.tid, dry_run=args.dry_run)
            logger.info("Publish-dir job completed: video_file=%s", result["video_file"])
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
