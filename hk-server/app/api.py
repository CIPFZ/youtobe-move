from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.discovery.repository import (
    count_videos,
    get_storage_stats,
    get_video_by_id,
    init_db,
    list_videos,
    mark_cleaned,
)
from app.settings import settings

logger = logging.getLogger(__name__)


# ── helpers ──

def _json_response(handler: BaseHTTPRequestHandler, data: object, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _error_response(handler: BaseHTTPRequestHandler, message: str, status: int = 400) -> None:
    _json_response(handler, {'error': True, 'message': message}, status=status)


def _check_auth(handler: BaseHTTPRequestHandler) -> bool:
    token = settings.api_token.strip()
    if not token:
        return True  # no auth required
    auth = handler.headers.get('Authorization', '')
    parts = auth.split()
    if len(parts) == 2 and parts[0].lower() == 'bearer' and parts[1] == token:
        return True
    _error_response(handler, 'Unauthorized', status=401)
    return False


def _stream_file(handler: BaseHTTPRequestHandler, disk_path: Path, content_type: str = 'application/octet-stream') -> None:
    """Stream a file with Range support (resume), zero-copy via sendfile."""
    if not disk_path.exists():
        _error_response(handler, 'File not found on disk', status=404)
        return

    file_size = disk_path.stat().st_size
    range_header = handler.headers.get('Range', '')
    start = 0
    end = file_size - 1

    if range_header.startswith('bytes='):
        try:
            r = range_header[6:]
            if '-' in r:
                parts = r.split('-', 1)
                if parts[0]:
                    start = int(parts[0])
                if parts[1]:
                    end = int(parts[1])
                if start < 0 or start >= file_size:
                    _error_response(handler, 'Range Not Satisfiable', status=416)
                    return
                end = min(end, file_size - 1)
        except (ValueError, IndexError):
            pass  # malformed range → serve full file

    content_length = end - start + 1
    is_partial = (start != 0 or end != file_size - 1)

    if is_partial:
        handler.send_response(206)
        handler.send_header('Content-Range', f'bytes {start}-{end}/{file_size}')
    else:
        handler.send_response(200)
    handler.send_header('Content-Type', content_type)
    handler.send_header('Content-Length', str(content_length))
    handler.send_header('Accept-Ranges', 'bytes')
    handler.end_headers()

    # stream file — use sendfile on Linux, fallback to chunked copy
    with disk_path.open('rb') as fsrc:
        if start > 0:
            fsrc.seek(start)

        if hasattr(os, 'sendfile'):
            # Linux sendfile(out_fd, in_fd, offset, count)
            try:
                fd = fsrc.fileno()
                sock_fd = handler.wfile.fileno()
                offset = start
                remaining = content_length
                while remaining > 0:
                    sent = os.sendfile(sock_fd, fd, offset, remaining)
                    if sent == 0:
                        break
                    offset += sent
                    remaining -= sent
                return
            except (OSError, TypeError, AttributeError):
                pass  # fallback to chunked copy

        # fallback: chunked copy (works everywhere)
        remaining = content_length
        while remaining > 0:
            chunk = fsrc.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            handler.wfile.write(chunk)
            remaining -= len(chunk)
            remaining -= sent


# ── path helpers ──

def _parse_video_id(path: str) -> str | None:
    """Extract video_id from path like /api/videos/abc123/file or /api/videos/abc123"""
    parts = [p for p in path.split('/') if p]
    if len(parts) >= 3 and parts[0] == 'api' and parts[1] == 'videos':
        return parts[2]
    return None


# ── request handler ──

class _ApiHandler(BaseHTTPRequestHandler):

    def do_GET(self) -> None:
        if not _check_auth(self):
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        qs = parse_qs(parsed.query)

        # GET /api/videos — list
        if path == '/api/videos':
            self._handle_list_videos(qs)
            return

        # GET /api/videos/<id> — detail or file
        if path.startswith('/api/videos/'):
            video_id = _parse_video_id(path)
            if not video_id or video_id == 'file':
                _error_response(self, 'Invalid video_id', status=400)
                return
            # check for /meta sub-path
            parts = [p for p in path.split('/') if p]
            if len(parts) >= 4 and parts[3] == 'meta':
                self._handle_get_meta(video_id)
                return
            # check for /file sub-path

            if len(parts) >= 4 and parts[3] == 'file':
                file_type = qs.get('type', ['video'])[0].lower()
                self._handle_get_file(video_id, file_type)
                return
            self._handle_get_video(video_id)
            return

        # GET /api/stats
        if path == '/api/stats':
            self._handle_stats()
            return

        _error_response(self, 'Not found', status=404)

    def do_DELETE(self) -> None:
        if not _check_auth(self):
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path.startswith('/api/videos/'):
            video_id = _parse_video_id(path)
            if not video_id:
                _error_response(self, 'Invalid video_id', status=400)
                return
            self._handle_delete_video(video_id)
            return

        _error_response(self, 'Not found', status=404)

    def do_POST(self) -> None:
        if not _check_auth(self):
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path == '/api/trigger-discovery':
            self._handle_trigger_discovery()
            return

        if path == '/api/download':
            self._handle_post_download()
            return

        _error_response(self, 'Not found', status=404)

    # ── handler methods ──

    def _handle_list_videos(self, qs: dict[str, list[str]]) -> None:
        category = (qs.get('category') or [''])[0].strip()
        ds = (qs.get('download_status') or [''])[0].strip()
        min_score = float((qs.get('min_score') or ['0'])[0] or 0)
        limit = int((qs.get('limit') or ['50'])[0] or 50)
        offset = int((qs.get('offset') or ['0'])[0] or 0)

        db_path = settings.discovery_db_path.resolve()
        total = count_videos(db_path, category=category, download_status=ds, min_score=min_score)
        videos = list_videos(
            db_path, category=category, download_status=ds,
            min_score=min_score, limit=limit, offset=offset,
        )

        _json_response(self, {
            'videos': videos,
            'total': total,
            'limit': limit,
            'offset': offset,
        })

    def _handle_get_video(self, video_id: str) -> None:
        db_path = settings.discovery_db_path.resolve()
        v = get_video_by_id(db_path, video_id)
        if v is None:
            _error_response(self, 'Video not found', status=404)
            return
        _json_response(self, {'video': v})

    def _handle_get_file(self, video_id: str, file_type: str) -> None:
        db_path = settings.discovery_db_path.resolve()
        v = get_video_by_id(db_path, video_id)
        if v is None:
            _error_response(self, 'Video not found', status=404)
            return

        file_path_str = v.get('file_path', '') or ''
        if not file_path_str:
            _error_response(self, 'Video not downloaded yet', status=404)
            return

        disk_path = Path(file_path_str)
        if not disk_path.is_dir():
            _error_response(self, 'Download directory missing', status=404)
            return

        if file_type == 'video':
            candidate = sorted(disk_path.glob('*.mp4'))
            if candidate:
                _stream_file(self, candidate[0], 'video/mp4')
                return
        elif file_type == 'audio':
            candidate = sorted(disk_path.glob('*.m4a'))
            if candidate:
                _stream_file(self, candidate[0], 'audio/mp4')
                return
        elif file_type == 'thumbnail':
            candidate = sorted(disk_path.glob('*.thumbnail.*'))
            if candidate:
                ext = candidate[0].suffix.lower()
                ct_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'}
                content_type = ct_map.get(ext, 'image/jpeg')
                _stream_file(self, candidate[0], content_type)
                return

        _error_response(self, f'No {file_type} file found for this video', status=404)

    def _handle_get_meta(self, video_id: str) -> None:
        db_path = settings.discovery_db_path.resolve()
        v = get_video_by_id(db_path, video_id)
        if v is None:
            _error_response(self, 'Video not found', status=404)
            return

        file_path_str = v.get('file_path', '') or ''
        if not file_path_str:
            _error_response(self, 'Video not downloaded yet', status=404)
            return

        disk_path = Path(file_path_str)
        if not disk_path.is_dir():
            _error_response(self, 'Download directory missing', status=404)
            return

        json_files = sorted(disk_path.glob('*.video_info.json'))
        if not json_files:
            _error_response(self, 'Metadata JSON not found for this video', status=404)
            return

        try:
            data = json.loads(json_files[0].read_text(encoding='utf-8'))
        except Exception as exc:
            _error_response(self, f'Failed to read metadata: {exc}', status=500)
            return

        _json_response(self, data)

    def _handle_delete_video(self, video_id: str) -> None:
        db_path = settings.discovery_db_path.resolve()
        v = get_video_by_id(db_path, video_id)
        if v is None:
            _error_response(self, 'Video not found', status=404)
            return

        # delete disk files
        file_path_str = v.get('file_path', '') or ''
        if file_path_str:
            disk_path = Path(file_path_str)
            if disk_path.exists():
                try:
                    if disk_path.is_dir():
                        shutil.rmtree(disk_path)
                    else:
                        disk_path.unlink()
                except OSError as exc:
                    _error_response(self, f'Failed to delete files: {exc}', status=500)
                    return

        mark_cleaned(db_path, video_id)
        _json_response(self, {'deleted': True, 'video_id': video_id})

    def _handle_stats(self) -> None:
        db_path = settings.discovery_db_path.resolve()
        stats = get_storage_stats(db_path)
        _json_response(self, stats)

    def _handle_trigger_discovery(self) -> None:
        """Start discovery+download in a background thread, return immediately."""
        def _bg() -> None:
            from app.download_service import run_discovery_and_download
            try:
                summary = run_discovery_and_download()
                logger.info('Manual trigger discovery complete: %s', summary)
            except Exception as exc:
                logger.error('Manual trigger discovery failed: %s', exc, exc_info=True)

        t = threading.Thread(target=_bg, daemon=True)
        t.start()
        _json_response(self, {'started': True, 'message': 'Discovery + download triggered in background'})

    def _handle_post_download(self) -> None:
        """POST /api/download — download a specific YouTube URL.

        Body: {"url": "https://www.youtube.com/watch?v=xxx", "category": "pets"}
        Returns video_id immediately, download runs in background.
        """
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            _error_response(self, 'Empty request body', status=400)
            return

        try:
            body = json.loads(self.rfile.read(content_length))
        except Exception:
            _error_response(self, 'Invalid JSON body', status=400)
            return

        url = str(body.get('url', '') or '').strip()
        if not url:
            _error_response(self, '"url" is required', status=400)
            return

        category = str(body.get('category', 'manual') or 'manual').strip()

        def _bg() -> None:
            try:
                from app.discovery.repository import (
                    ensure_video_row, init_db, mark_downloaded, mark_download_failed, mark_downloading,
                )
                from app.disk_cleaner import cleanup_if_needed
                from app.downloader import download_media
                from pathlib import Path

                db_path = settings.discovery_db_path.resolve()
                media_root = settings.download_media_dir.resolve()
                init_db(db_path)

                # extract video_id from URL
                import re as _re
                m = _re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', url)
                if not m:
                    logger.error('Could not extract video_id from URL: %s', url)
                    return
                vid = m.group(1)

                out_dir = media_root / category / vid
                out_dir.mkdir(parents=True, exist_ok=True)

                # ensure DB row exists (for manual downloads that skip discovery)
                ensure_video_row(db_path, vid, url, category)
                mark_downloading(db_path, vid)

                result = download_media(
                    url=url,
                    out_dir=out_dir,
                    cookie_file=settings.cookie_file,
                    proxy_url=settings.ytdlp_proxy,
                    playlist_strategy=settings.playlist_strategy,
                )
                total_size = sum(
                    f.stat().st_size for f in out_dir.rglob('*') if f.is_file()
                )
                mark_downloaded(db_path, vid, str(out_dir), total_size)
                logger.info('Manual download OK: %s (%s) size=%d', vid, url, total_size)

                cleanup_if_needed(
                    db_path=db_path, media_dir=media_root,
                    max_gb=settings.disk_max_storage_gb,
                    max_days=settings.disk_max_retention_days,
                )
            except Exception as exc:
                logger.error('Manual download failed: %s err=%s', url, exc)

        t = threading.Thread(target=_bg, daemon=True)
        t.start()

        # extract video_id for response
        import re as _re
        m = _re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})', url)
        video_id = m.group(1) if m else ''
        _json_response(self, {'started': True, 'video_id': video_id, 'url': url})

    def log_message(self, fmt: str, *args: object) -> None:
        logger.debug('API %s', fmt % args)


# ── server runner ──

def run_api_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    """Start the HTTP API server. Returns the server instance.

    Call ``server.serve_forever()`` to block, or use in a background thread.
    """
    h = host or settings.api_host
    p = port or settings.api_port
    db = settings.discovery_db_path.resolve()

    init_db(db)
    logger.info('API server starting on %s:%d (db=%s)', h, p, db)

    server = ThreadingHTTPServer((h, p), _ApiHandler)
    server._db_path = db
    return server
