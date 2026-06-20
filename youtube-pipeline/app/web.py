from __future__ import annotations

import json
import logging
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.config import Config, load_config
from app.config_service import list_config, update_config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.discovery import discover_videos
from app.discovery.service import preview_discovery_source
from app.discovery.source_config import (
    add_discovery_source,
    delete_discovery_source,
    list_discovery_source_configs,
    replace_discovery_sources,
    update_discovery_source,
)
from app.download_service import download_next, download_video_from_db
from app.operations import add_video_url, add_video_urls, pipeline_status, retry_video, skip_video
from app.publish_service import describe_video, publish_next, publish_video, review_publish_draft, update_publish_draft
from app.storage import cleanup_media, cleanup_video_media, get_storage_status
from app.worker import run_worker_once
from app.youtube_api import parse_video_id


logger = logging.getLogger("youtube-pipeline")

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
REACT_DIST_DIR = PROJECT_DIR / "web" / "dist"
LEGACY_STATIC_DIR = PACKAGE_DIR / "web_static"


class WebError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


class PipelineHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler], config: Config):
        super().__init__(server_address, handler_class)
        self.config = config


def _json_loads(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise WebError(HTTPStatus.BAD_REQUEST, f"Invalid JSON body: {exc}") from exc
    if not isinstance(value, dict):
        raise WebError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
    return value


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, default: int, minimum: int = 0, maximum: int = 500) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise WebError(HTTPStatus.BAD_REQUEST, f"Invalid integer: {value}") from exc
    return min(max(parsed, minimum), maximum)


def _video_detail(config: Config, video_id: str) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        video = repo.get_video(video_id)
        if video is None:
            raise WebError(HTTPStatus.NOT_FOUND, f"Video not found: {video_id}")
        return {
            "video": video,
            "media_files": repo.get_media_files(video_id),
            "latest_download_job": repo.get_latest_job(video_id, "download"),
            "latest_describe_job": repo.get_latest_job(video_id, "describe"),
            "latest_publish_job": repo.get_latest_job(video_id, "publish"),
            "publish_draft": repo.get_publish_draft(video_id, "bilibili"),
            "publish_records": repo.list_publish_records(video_id),
            "events": repo.list_events(video_id=video_id, limit=30),
        }


def _list_videos(config: Config, query: dict[str, list[str]]) -> dict[str, Any]:
    status = (query.get("status") or [""])[0] or None
    draft_status = (query.get("draft_status") or [""])[0] or None
    error_type = (query.get("error_type") or [""])[0] or None
    limit = _parse_int((query.get("limit") or [""])[0], 50, minimum=1, maximum=200)
    offset = _parse_int((query.get("offset") or [""])[0], 0, minimum=0, maximum=100000)
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        fetch_limit = limit if not (draft_status or error_type) else 500
        videos = repo.list_videos(status=status, limit=fetch_limit, offset=offset)
        rows: list[dict[str, Any]] = []
        for video in videos:
            video_id = str(video["video_id"])
            latest_download_job = repo.get_latest_job(video_id, "download")
            latest_describe_job = repo.get_latest_job(video_id, "describe")
            latest_publish_job = repo.get_latest_job(video_id, "publish")
            latest_jobs = [job for job in (latest_download_job, latest_describe_job, latest_publish_job) if job]
            publish_draft = repo.get_publish_draft(video_id, "bilibili")
            if draft_status and str((publish_draft or {}).get("status") or "") != draft_status:
                continue
            if error_type and not any(str(job.get("error_type") or "") == error_type for job in latest_jobs):
                continue
            rows.append(
                {
                    "video": video,
                    "media_files": repo.get_media_files(video_id),
                    "publish_draft": publish_draft,
                    "latest_download_job": latest_download_job,
                    "latest_describe_job": latest_describe_job,
                    "latest_publish_job": latest_publish_job,
                    "publish_records": repo.list_publish_records(video_id),
                }
            )
    return {
        "videos": rows[:limit],
        "limit": limit,
        "offset": offset,
        "status": status,
        "draft_status": draft_status,
        "error_type": error_type,
    }


def _status_settings(config: Config) -> dict[str, Any]:
    return {
        "pipeline_enabled": config.pipeline_enabled,
        "publish_mode": config.publish_mode,
        "worker_interval_seconds": config.worker_interval_seconds,
        "worker_cron": config.worker_cron,
        "worker_enable_discovery": config.worker_enable_discovery,
        "worker_enable_download": config.worker_enable_download,
        "worker_enable_describe": config.worker_enable_describe,
        "worker_enable_publish": config.worker_enable_publish,
        "worker_publish_dry_run": config.worker_publish_dry_run,
        "worker_discovery_min_queue_size": config.worker_discovery_min_queue_size,
        "worker_discovery_source": config.worker_discovery_source,
        "job_lease_seconds": config.job_lease_seconds,
        "publish_min_interval_seconds": config.publish_min_interval_seconds,
        "publish_daily_limit": config.publish_daily_limit,
        "publish_window_start": config.publish_window_start,
        "publish_window_end": config.publish_window_end,
    }


def _list_events(config: Config, query: dict[str, list[str]]) -> dict[str, Any]:
    limit = _parse_int((query.get("limit") or [""])[0], 50, minimum=1, maximum=200)
    offset = _parse_int((query.get("offset") or [""])[0], 0, minimum=0, maximum=100000)
    module = (query.get("module") or [""])[0].strip() or None
    video_id = (query.get("video_id") or [""])[0].strip() or None
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        events = repo.list_events(video_id=video_id, module=module, limit=limit, offset=offset)
    return {
        "events": events,
        "limit": limit,
        "offset": offset,
        "module": module,
        "video_id": video_id,
        "has_more": len(events) == limit,
    }


def _list_failures(config: Config, query: dict[str, list[str]]) -> dict[str, Any]:
    limit = _parse_int((query.get("limit") or [""])[0], 30, minimum=1, maximum=200)
    offset = _parse_int((query.get("offset") or [""])[0], 0, minimum=0, maximum=100000)
    job_type = (query.get("job_type") or [""])[0].strip() or None
    error_type = (query.get("error_type") or [""])[0].strip() or None
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        failures = repo.list_failures(limit=limit, offset=offset, job_type=job_type, error_type=error_type)
    return {
        "failures": failures,
        "limit": limit,
        "offset": offset,
        "job_type": job_type,
        "error_type": error_type,
        "has_more": len(failures) == limit,
    }


def _media_file_response(config: Config, video_id: str, file_type: str) -> tuple[Path, str]:
    media_files = _video_detail(config, video_id)["media_files"]
    if not media_files:
        raise WebError(HTTPStatus.NOT_FOUND, f"Media files not found: {video_id}")
    key_by_type = {
        "meta": "meta_path",
        "video": "video_path",
        "audio": "audio_path",
        "poster": "poster_path",
        "merged": "merged_path",
    }
    key = key_by_type.get(file_type)
    if key is None:
        raise WebError(HTTPStatus.BAD_REQUEST, f"Unsupported file type: {file_type}")
    raw_path = str(media_files.get(key) or "")
    if not raw_path:
        raise WebError(HTTPStatus.NOT_FOUND, f"File type not available: {file_type}")
    path = config.resolve_path(raw_path)
    if not path.exists() or not path.is_file():
        raise WebError(HTTPStatus.NOT_FOUND, f"File not found: {raw_path}")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path, content_type


def _handle_action(config: Config, video_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    if action == "approve":
        return review_publish_draft(video_id, config, "approved", note=str(body.get("note") or ""))
    if action == "reject":
        return review_publish_draft(video_id, config, "rejected", note=str(body.get("note") or ""))
    if action == "retry":
        job_type = body.get("job_type") or None
        return retry_video(video_id, config, job_type=job_type)
    if action == "skip":
        return skip_video(video_id, config, force=bool(body.get("force", False)))
    if action == "download":
        return download_video_from_db(video_id, config, force=bool(body.get("force", False)))
    if action == "describe":
        return describe_video(video_id, config, force=bool(body.get("force", False)))
    if action == "publish-dry-run":
        return publish_video(video_id, config, dry_run=True, force=bool(body.get("force", False)))
    if action == "publish":
        if body.get("confirm") is not True:
            raise WebError(HTTPStatus.BAD_REQUEST, "Real publish requires confirm=true")
        return publish_video(video_id, config, dry_run=False, force=bool(body.get("force", False)))
    raise WebError(HTTPStatus.NOT_FOUND, f"Unknown action: {action}")


def _handle_batch_action(config: Config, action: str, video_ids: list[str], body: dict[str, Any]) -> dict[str, Any]:
    if action not in {"approve", "reject", "retry", "skip"}:
        raise WebError(HTTPStatus.BAD_REQUEST, f"Unsupported batch action: {action}")
    if not video_ids:
        raise WebError(HTTPStatus.BAD_REQUEST, "video_ids is required")
    if len(video_ids) > 100:
        raise WebError(HTTPStatus.BAD_REQUEST, "At most 100 videos can be processed at once")

    results: list[dict[str, Any]] = []
    for raw_video_id in video_ids:
        try:
            video_id = parse_video_id(str(raw_video_id))
            result = _handle_action(config, video_id, action, body)
            results.append({"video_id": video_id, "status": "ok", "result": result})
        except Exception as exc:
            results.append({"video_id": str(raw_video_id), "status": "error", "error": str(exc)})
    return {
        "status": "ok" if all(item["status"] == "ok" for item in results) else "partial",
        "action": action,
        "total": len(results),
        "success_count": sum(1 for item in results if item["status"] == "ok"),
        "error_count": sum(1 for item in results if item["status"] == "error"),
        "results": results,
    }


class PipelineRequestHandler(BaseHTTPRequestHandler):
    server: PipelineHTTPServer

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("web %s - %s", self.address_string(), fmt % args)

    @property
    def config(self) -> Config:
        return self.server.config

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_PATCH(self) -> None:
        self._handle("PATCH")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def _handle(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if method == "GET" and path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            if method == "GET" and path == "/":
                self._send_static(_static_root() / "index.html")
                return
            if method == "GET" and (path.startswith("/static/") or path.startswith("/assets/")):
                prefix = "/static/" if path.startswith("/static/") else "/"
                relative = Path(unquote(path.removeprefix(prefix)))
                if relative.is_absolute() or ".." in relative.parts:
                    raise WebError(HTTPStatus.BAD_REQUEST, "Invalid static path")
                self._send_static(_static_root() / relative)
                return
            if path.startswith("/api/"):
                self._handle_api(method, path, query)
                return
            raise WebError(HTTPStatus.NOT_FOUND, "Not found")
        except WebError as exc:
            self._send_json({"error": exc.message}, status=exc.status)
        except Exception as exc:
            logger.exception("Web request failed: method=%s path=%s", method, self.path)
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle_api(self, method: str, path: str, query: dict[str, list[str]]) -> None:
        body = self._read_body() if method in {"POST", "PATCH", "DELETE"} else {}
        parts = [part for part in path.split("/") if part]

        if method == "GET" and path == "/api/status":
            limit = _parse_int((query.get("events_limit") or [""])[0], 20, minimum=0, maximum=100)
            result = pipeline_status(self.config, events_limit=limit)
            result["settings"] = _status_settings(self.config)
            self._send_json(result)
            return

        if method == "GET" and path == "/api/config":
            self._send_json(list_config(self.config.base_dir))
            return

        if method == "GET" and path == "/api/events":
            self._send_json(_list_events(self.config, query))
            return

        if method == "GET" and path == "/api/failures":
            self._send_json(_list_failures(self.config, query))
            return

        if method == "GET" and path == "/api/storage":
            self._send_json(get_storage_status(self.config))
            return

        if method == "POST" and path == "/api/storage/cleanup":
            dry_run = bool(body.get("dry_run", True))
            if not dry_run and body.get("confirm") is not True:
                raise WebError(HTTPStatus.BAD_REQUEST, "Storage cleanup requires confirm=true")
            self._send_json(cleanup_media(self.config, dry_run=dry_run))
            return

        if method == "PATCH" and path == "/api/config":
            updates = body.get("values", body)
            if not isinstance(updates, dict):
                raise WebError(HTTPStatus.BAD_REQUEST, "Config updates must be an object")
            try:
                result = update_config(updates, self.config.base_dir, actor="web")
            except ValueError as exc:
                raise WebError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
            self.server.config = load_config()
            self._send_json(result)
            return

        if method == "GET" and path == "/api/videos":
            self._send_json(_list_videos(self.config, query))
            return

        if method == "POST" and path == "/api/videos/add-url":
            url = str(body.get("url") or "").strip()
            if not url:
                raise WebError(HTTPStatus.BAD_REQUEST, "url is required")
            status = str(body.get("status") or "selected")
            priority = int(body.get("priority") or 100)
            source_label = str(body.get("source_label") or "web")
            self._send_json(add_video_url(url, self.config, status=status, source="web", priority=priority, source_label=source_label))
            return

        if method == "POST" and path == "/api/videos/add-urls":
            raw_urls = body.get("urls")
            if isinstance(raw_urls, str):
                urls = [line.strip() for line in raw_urls.splitlines()]
            elif isinstance(raw_urls, list):
                urls = [str(url).strip() for url in raw_urls]
            else:
                raise WebError(HTTPStatus.BAD_REQUEST, "urls must be a string or list")
            status = str(body.get("status") or "selected")
            priority = int(body.get("priority") or 100)
            source_label = str(body.get("source_label") or "web")
            self._send_json(add_video_urls(urls, self.config, status=status, source="web", priority=priority, source_label=source_label))
            return

        if method == "POST" and path == "/api/videos/batch":
            action = str(body.get("action") or "").strip()
            raw_video_ids = body.get("video_ids")
            if not isinstance(raw_video_ids, list):
                raise WebError(HTTPStatus.BAD_REQUEST, "video_ids must be a list")
            self._send_json(
                _handle_batch_action(
                    self.config,
                    action,
                    [str(video_id) for video_id in raw_video_ids],
                    body,
                )
            )
            return

        if method == "POST" and path == "/api/discover":
            source = body.get("source") or None
            dry_run = bool(body.get("dry_run", False))
            self._send_json(discover_videos(self.config, source_type=source, dry_run=dry_run))
            return

        if method == "GET" and path == "/api/discovery/sources":
            self._send_json(list_discovery_source_configs(self.config))
            return

        if method == "PATCH" and path == "/api/discovery/sources":
            sources = body.get("sources")
            if not isinstance(sources, list):
                raise WebError(HTTPStatus.BAD_REQUEST, "sources must be a list")
            try:
                result = replace_discovery_sources(self.config, sources)
            except ValueError as exc:
                raise WebError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
            self.server.config = load_config()
            self._send_json(result)
            return

        if method == "POST" and path == "/api/discovery/sources":
            source = body.get("source", body)
            if not isinstance(source, dict):
                raise WebError(HTTPStatus.BAD_REQUEST, "source must be an object")
            try:
                result = add_discovery_source(self.config, source)
            except ValueError as exc:
                raise WebError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
            self.server.config = load_config()
            self._send_json(result)
            return

        if len(parts) == 4 and parts[:3] == ["api", "discovery", "sources"]:
            try:
                index = int(parts[3])
                if method == "PATCH":
                    result = update_discovery_source(self.config, index, body)
                elif method == "DELETE":
                    result = delete_discovery_source(self.config, index)
                elif method == "POST" and body.get("action") == "preview":
                    result = preview_discovery_source(self.config, index)
                else:
                    raise WebError(HTTPStatus.NOT_FOUND, "Not found")
            except (ValueError, IndexError) as exc:
                raise WebError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
            self.server.config = load_config()
            self._send_json(result)
            return

        if method == "POST" and path == "/api/worker-run":
            enable_publish = body.get("enable_publish")
            publish_dry_run = body.get("publish_dry_run")
            self._send_json(
                run_worker_once(
                    self.config,
                    enable_publish=enable_publish if isinstance(enable_publish, bool) else None,
                    publish_dry_run=publish_dry_run if isinstance(publish_dry_run, bool) else None,
                )
            )
            return

        if method == "POST" and path == "/api/download-next":
            self._send_json(download_next(self.config, force=bool(body.get("force", False))))
            return

        if method == "POST" and path == "/api/publish-next":
            if body.get("confirm") is not True and not bool(body.get("dry_run", False)):
                raise WebError(HTTPStatus.BAD_REQUEST, "Real publish-next requires confirm=true")
            self._send_json(
                publish_next(
                    self.config,
                    dry_run=bool(body.get("dry_run", False)),
                    force=bool(body.get("force", False)),
                )
            )
            return

        if len(parts) >= 3 and parts[1] == "videos":
            video_id = parse_video_id(unquote(parts[2]))
            if method == "GET" and len(parts) == 3:
                self._send_json(_video_detail(self.config, video_id))
                return
            if method == "GET" and len(parts) == 4 and parts[3] == "file":
                file_type = (query.get("type") or ["merged"])[0]
                path, content_type = _media_file_response(self.config, video_id, file_type)
                self._send_file(path, content_type)
                return
            if method == "PATCH" and len(parts) == 4 and parts[3] == "draft":
                try:
                    self._send_json(
                        update_publish_draft(
                            video_id=video_id,
                            config=self.config,
                            title=str(body.get("title") or ""),
                            description=str(body.get("description") or ""),
                            tags=body.get("tags") or [],
                            tid=int(body.get("tid")),
                            status=str(body.get("status") or "pending"),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    raise WebError(HTTPStatus.BAD_REQUEST, str(exc)) from exc
                return
            if method == "POST" and len(parts) == 4 and parts[3] == "cleanup-media":
                dry_run = bool(body.get("dry_run", True))
                if not dry_run and body.get("confirm") is not True:
                    raise WebError(HTTPStatus.BAD_REQUEST, "Media cleanup requires confirm=true")
                self._send_json(
                    cleanup_video_media(
                        self.config,
                        video_id,
                        dry_run=dry_run,
                        force=bool(body.get("force", False)),
                    )
                )
                return
            if method == "POST" and len(parts) == 4:
                self._send_json(_handle_action(self.config, video_id, parts[3], body))
                return

        raise WebError(HTTPStatus.NOT_FOUND, "Not found")

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return _json_loads(self.rfile.read(length))

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            logger.info("web client disconnected while sending JSON")

    def _send_static(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            raise WebError(HTTPStatus.NOT_FOUND, "Static file not found")
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send_file(path, content_type)

    def _send_file(self, path: Path, content_type: str) -> None:
        stat = path.stat()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(stat.st_size))
        self.end_headers()
        with path.open("rb") as file:
            while chunk := file.read(1024 * 1024):
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    logger.info("web client disconnected while streaming file: %s", path)
                    break


def run_web_server(config: Config, host: str | None = None, port: int | None = None) -> None:
    bind_host = host or config.web_host
    bind_port = port or config.web_port
    server = PipelineHTTPServer((bind_host, bind_port), PipelineRequestHandler, config)
    logger.info("Web management UI started: http://%s:%s", bind_host, bind_port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _static_root() -> Path:
    index_path = REACT_DIST_DIR / "index.html"
    if index_path.exists():
        return REACT_DIST_DIR
    return LEGACY_STATIC_DIR
