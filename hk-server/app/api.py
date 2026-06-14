from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.discovery.providers.base import UnsupportedProviderError
from app.discovery.repository import (
    acquire_pull_lock,
    count_video_events,
    count_videos,
    get_storage_stats,
    get_video_by_id,
    init_db,
    list_video_events,
    list_videos,
    mark_published,
    mark_pulled,
    release_pull_lock,
)
from app.settings import settings
from app.task_state import finish_task, get_task_state, try_start_task
from app.tasks import (
    count_tasks,
    get_task,
    init_task_db,
    list_task_events,
    list_tasks,
    recover_interrupted_tasks,
    request_cancel,
)

logger = logging.getLogger(__name__)


# ── helpers ──

def _json_response(handler: BaseHTTPRequestHandler, data: object, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _success_response(handler: BaseHTTPRequestHandler, data: object, status: int = 200) -> None:
    _json_response(handler, {'ok': True, 'data': data}, status=status)


def _error_response(
    handler: BaseHTTPRequestHandler,
    message: str,
    status: int = 400,
    code: str = '',
    details: object | None = None,
) -> None:
    if not code:
        code = {
            400: 'bad_request',
            401: 'unauthorized',
            404: 'not_found',
            409: 'conflict',
            416: 'range_not_satisfiable',
            500: 'internal_error',
            503: 'unavailable',
        }.get(status, 'error')
    error: dict[str, object] = {'code': code, 'message': message}
    if details is not None:
        error['details'] = details
    _json_response(handler, {'ok': False, 'error': error}, status=status)


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


# ── path helpers ──

def _parse_video_id(path: str) -> str | None:
    """Extract video_id from path like /api/videos/abc123/file or /api/videos/abc123"""
    parts = [p for p in path.split('/') if p]
    if len(parts) >= 3 and parts[0] == 'api' and parts[1] == 'videos':
        return parts[2]
    return None


def _parse_task_id(path: str) -> int | None:
    parts = [p for p in path.split('/') if p]
    if len(parts) >= 3 and parts[0] == 'api' and parts[1] == 'tasks':
        try:
            return int(parts[2])
        except ValueError:
            return None
    return None


def _extract_youtube_video_id(url: str) -> str:
    import re

    m = re.search(r'(?:v=|/)([a-zA-Z0-9_-]{11})(?:[&#?/]|$)', url)
    return m.group(1) if m else ''


# ── request handler ──

class _ApiHandler(BaseHTTPRequestHandler):

    def do_GET(self) -> None:
        if not _check_auth(self):
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')
        qs = parse_qs(parsed.query)

        # GET /api/videos — list
        if path == '/api/health':
            self._handle_health()
            return

        if path == '/api/tasks':
            self._handle_tasks(qs)
            return

        if path.startswith('/api/tasks/'):
            task_id = _parse_task_id(path)
            if task_id is None:
                _error_response(self, 'Invalid task_id', status=400)
                return
            self._handle_get_task(task_id)
            return

        if path == '/api/videos':
            self._handle_list_videos(qs)
            return

        if path == '/api/video-events':
            self._handle_list_video_events(qs)
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
            if len(parts) >= 4 and parts[3] == 'events':
                self._handle_get_video_events(video_id, qs)
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

        if path.startswith('/api/videos/') and path.endswith('/files'):
            video_id = _parse_video_id(path)
            if not video_id:
                _error_response(self, 'Invalid video_id', status=400)
                return
            self._handle_delete_video(video_id, mark_as='expired')
            return

        _error_response(self, 'Not found', status=404)

    def do_POST(self) -> None:
        if not _check_auth(self):
            return

        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        if path == '/api/discovery/run':
            self._handle_trigger_discovery()
            return

        if path == '/api/discovery/preview':
            self._handle_discovery_preview()
            return

        if path == '/api/downloads':
            self._handle_post_download()
            return

        if path.startswith('/api/tasks/'):
            task_id = _parse_task_id(path)
            parts = [p for p in path.split('/') if p]
            if task_id is None or len(parts) < 4:
                _error_response(self, 'Invalid task_id', status=400)
                return
            if parts[3] == 'cancel':
                self._handle_cancel_task(task_id)
                return
            if parts[3] == 'retry':
                self._handle_retry_task(task_id)
                return

        if path.startswith('/api/videos/'):
            video_id = _parse_video_id(path)
            parts = [p for p in path.split('/') if p]
            if video_id and len(parts) >= 4 and parts[3] == 'confirm-pulled':
                self._handle_confirm_pulled(video_id)
                return
            if video_id and len(parts) >= 4 and parts[3] == 'pull-lock':
                self._handle_pull_lock(video_id)
                return
            if video_id and len(parts) >= 4 and parts[3] == 'release-pull-lock':
                self._handle_release_pull_lock(video_id)
                return
            if video_id and len(parts) >= 4 and parts[3] == 'mark-published':
                self._handle_mark_published(video_id)
                return

        _error_response(self, 'Not found', status=404)

    # ── handler methods ──

    def _handle_list_videos(self, qs: dict[str, list[str]]) -> None:
        category = (qs.get('category') or [''])[0].strip()
        ds = (qs.get('download_status') or qs.get('status') or [''])[0].strip()
        min_score = float((qs.get('min_score') or ['0'])[0] or 0)
        limit = int((qs.get('limit') or ['50'])[0] or 50)
        offset = int((qs.get('offset') or ['0'])[0] or 0)

        db_path = settings.discovery_db_path.resolve()
        total = count_videos(db_path, category=category, download_status=ds, min_score=min_score)
        videos = list_videos(
            db_path, category=category, download_status=ds,
            min_score=min_score, limit=limit, offset=offset,
        )

        _success_response(self, {
            'items': videos,
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
        _success_response(self, v)

    def _parse_optional_int(self, raw: str, field_name: str) -> int | None:
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            _error_response(self, f'Invalid {field_name}', status=400)
            return None

    def _handle_list_video_events(self, qs: dict[str, list[str]]) -> None:
        video_id = (qs.get('video_id') or [''])[0].strip()
        task_id_raw = (qs.get('task_id') or [''])[0].strip()
        task_id = self._parse_optional_int(task_id_raw, 'task_id')
        if task_id_raw and task_id is None:
            return
        limit = int((qs.get('limit') or ['100'])[0] or 100)
        offset = int((qs.get('offset') or ['0'])[0] or 0)
        db_path = settings.discovery_db_path.resolve()
        _success_response(self, {
            'items': list_video_events(db_path, video_id, task_id=task_id, limit=limit, offset=offset),
            'total': count_video_events(db_path, video_id, task_id=task_id),
            'limit': limit,
            'offset': offset,
            'video_id': video_id,
            'task_id': task_id,
        })

    def _handle_get_video_events(self, video_id: str, qs: dict[str, list[str]]) -> None:
        db_path = settings.discovery_db_path.resolve()
        if get_video_by_id(db_path, video_id) is None:
            _error_response(self, 'Video not found', status=404)
            return
        task_id_raw = (qs.get('task_id') or [''])[0].strip()
        task_id = self._parse_optional_int(task_id_raw, 'task_id')
        if task_id_raw and task_id is None:
            return
        limit = int((qs.get('limit') or ['100'])[0] or 100)
        offset = int((qs.get('offset') or ['0'])[0] or 0)
        _success_response(self, {
            'items': list_video_events(db_path, video_id, task_id=task_id, limit=limit, offset=offset),
            'total': count_video_events(db_path, video_id, task_id=task_id),
            'limit': limit,
            'offset': offset,
            'video_id': video_id,
            'task_id': task_id,
        })

    def _handle_get_file(self, video_id: str, file_type: str) -> None:
        db_path = settings.discovery_db_path.resolve()
        v = get_video_by_id(db_path, video_id)
        if v is None:
            _error_response(self, 'Video not found', status=404)
            return

        file_path_str = v.get('file_dir', '') or v.get('file_path', '') or ''
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

        file_path_str = v.get('file_dir', '') or v.get('file_path', '') or ''
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

        _success_response(self, data)

    def _handle_delete_video(self, video_id: str, *, mark_as: str = 'pulled') -> None:
        db_path = settings.discovery_db_path.resolve()
        v = get_video_by_id(db_path, video_id)
        if v is None:
            _error_response(self, 'Video not found', status=404)
            return

        # delete disk files
        file_path_str = v.get('file_dir', '') or v.get('file_path', '') or ''
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

        if mark_as == 'pulled':
            mark_pulled(db_path, video_id)
            _success_response(self, {'deleted': True, 'status': 'pulled', 'video_id': video_id})
        else:
            from app.discovery.repository import mark_expired
            mark_expired(db_path, video_id)
            _success_response(self, {'deleted': True, 'status': 'expired', 'video_id': video_id})

    def _handle_confirm_pulled(self, video_id: str) -> None:
        self._handle_delete_video(video_id, mark_as='pulled')

    def _handle_pull_lock(self, video_id: str) -> None:
        body, error = self._read_json_body()
        if error:
            _error_response(self, error, status=400)
            return
        locked_by = (str((body or {}).get('locked_by') or 'local').strip() or 'local')[:200]
        ttl_raw = (body or {}).get('ttl_minutes', settings.pull_lock_ttl_minutes)
        try:
            ttl_minutes = int(ttl_raw)
        except (TypeError, ValueError):
            _error_response(self, 'Invalid ttl_minutes', status=400)
            return

        db_path = settings.discovery_db_path.resolve()
        locked = acquire_pull_lock(db_path, video_id, locked_by=locked_by, ttl_minutes=ttl_minutes)
        if locked is None:
            _error_response(self, 'Video not found', status=404)
            return
        if locked.get('status') != 'pulling' or locked.get('pull_locked_by') != locked_by:
            _error_response(
                self,
                'Video is not available for pulling',
                status=409,
                code='pull_lock_conflict',
                details={'video': locked},
            )
            return
        _success_response(self, locked)

    def _handle_release_pull_lock(self, video_id: str) -> None:
        body, error = self._read_json_body()
        if error:
            _error_response(self, error, status=400)
            return
        locked_by = str((body or {}).get('locked_by') or '').strip()[:200]
        db_path = settings.discovery_db_path.resolve()
        released = release_pull_lock(db_path, video_id, locked_by=locked_by)
        if released is None:
            _error_response(self, 'Video not found', status=404)
            return
        if released.get('status') == 'pulling':
            _error_response(
                self,
                'Pull lock is owned by another client',
                status=409,
                code='pull_lock_conflict',
                details={'video': released},
            )
            return
        _success_response(self, released)

    def _handle_mark_published(self, video_id: str) -> None:
        body, error = self._read_json_body()
        if error:
            _error_response(self, error, status=400)
            return
        platform = str((body or {}).get('platform') or '').strip()
        publish_ref = str((body or {}).get('publish_ref') or '').strip()
        db_path = settings.discovery_db_path.resolve()
        published = mark_published(db_path, video_id, platform=platform, publish_ref=publish_ref)
        if published is None:
            _error_response(self, 'Video not found', status=404)
            return
        _success_response(self, published)

    def _handle_health(self) -> None:
        db_path = settings.discovery_db_path.resolve()
        download_dir = settings.download_media_dir.resolve()
        db_ok = False
        db_error = ''
        try:
            init_db(db_path)
            db_ok = True
        except Exception as exc:
            db_error = str(exc)

        disk_free_gb = 0.0
        download_dir_ok = False
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(download_dir)
            disk_free_gb = round(usage.free / (1024 ** 3), 2)
            download_dir_ok = True
        except Exception:
            download_dir_ok = False

        data = {
            'service': 'hk-server',
            'db_ok': db_ok,
            'db_error': db_error,
            'download_dir_ok': download_dir_ok,
            'download_dir': str(download_dir),
            'disk_free_gb': disk_free_gb,
            'api_auth_enabled': bool(settings.api_token.strip()),
            'task': get_task_state(),
        }
        if db_ok and download_dir_ok:
            _success_response(self, data)
            return
        _error_response(
            self,
            'Health check failed',
            status=503,
            code='health_check_failed',
            details=data,
        )

    def _handle_tasks(self, qs: dict[str, list[str]]) -> None:
        status = (qs.get('status') or [''])[0].strip()
        task_name = (qs.get('type') or qs.get('task_name') or [''])[0].strip()
        limit = int((qs.get('limit') or ['50'])[0] or 50)
        offset = int((qs.get('offset') or ['0'])[0] or 0)
        db_path = settings.discovery_db_path.resolve()
        _success_response(self, {
            'items': list_tasks(db_path, status=status, task_name=task_name, limit=limit, offset=offset),
            'total': count_tasks(db_path, status=status, task_name=task_name),
            'limit': limit,
            'offset': offset,
            'current': get_task_state(),
        })

    def _handle_get_task(self, task_id: int) -> None:
        db_path = settings.discovery_db_path.resolve()
        task = get_task(db_path, task_id)
        if task is None:
            _error_response(self, 'Task not found', status=404)
            return
        task['events'] = list_task_events(db_path, task_id)
        _success_response(self, task)

    def _handle_cancel_task(self, task_id: int) -> None:
        db_path = settings.discovery_db_path.resolve()
        task = request_cancel(db_path, task_id)
        if task is None:
            _error_response(self, 'Task not found', status=404)
            return
        _success_response(self, task)

    def _handle_retry_task(self, task_id: int) -> None:
        db_path = settings.discovery_db_path.resolve()
        old_task = get_task(db_path, task_id)
        if old_task is None:
            _error_response(self, 'Task not found', status=404)
            return

        input_data = dict(old_task.get('input') or {})
        input_data['retry_of'] = task_id
        task_name = str(old_task.get('task_name') or '')
        if task_name == 'discovery_download':
            self._start_discovery_task(input_data=input_data)
            return
        if task_name == 'manual_download':
            url = str(input_data.get('url') or '').strip()
            category = str(input_data.get('category') or 'manual').strip()
            vid = str(input_data.get('video_id') or _extract_youtube_video_id(url)).strip()
            if not url or not vid:
                _error_response(self, 'Original manual download task has invalid input', status=400)
                return
            self._start_manual_download(url=url, category=category, vid=vid, input_data=input_data)
            return
        _error_response(self, f'Task type is not retryable: {task_name}', status=400)

    def _handle_stats(self) -> None:
        db_path = settings.discovery_db_path.resolve()
        stats = get_storage_stats(db_path)
        _success_response(self, stats)

    def _handle_trigger_discovery(self) -> None:
        """Start discovery+download in a background thread, return immediately."""
        self._start_discovery_task()

    def _read_json_body(self) -> tuple[dict[str, object] | None, str]:
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}, ''
        try:
            body = json.loads(self.rfile.read(content_length))
        except Exception:
            return None, 'Invalid JSON body'
        if not isinstance(body, dict):
            return None, 'JSON body must be an object'
        return body, ''

    def _handle_discovery_preview(self) -> None:
        body, error = self._read_json_body()
        if error:
            _error_response(self, error, status=400)
            return

        top_n_raw = body.get('top_n') if body else None
        top_n = 0
        if top_n_raw not in (None, ''):
            try:
                top_n = int(top_n_raw)
            except (TypeError, ValueError):
                _error_response(self, 'Invalid top_n', status=400)
                return
            if top_n < 0:
                _error_response(self, 'Invalid top_n', status=400)
                return

        try:
            from app.discovery.service import discovery_preview
            _success_response(self, discovery_preview(top_n=top_n))
        except UnsupportedProviderError as exc:
            _error_response(self, str(exc), status=400, code='unsupported_provider')
        except Exception as exc:
            logger.error('Discovery preview failed: %s', exc, exc_info=True)
            _error_response(self, f'Discovery preview failed: {exc}', status=500)

    def _start_discovery_task(self, input_data: dict[str, object] | None = None) -> None:
        task = try_start_task('discovery_download', input_data=input_data)
        if task is None:
            _error_response(
                self,
                'A background task is already running',
                status=409,
                code='task_running',
                details={'task': get_task_state()},
            )
            return

        def _bg() -> None:
            runner_started = False
            try:
                from app.download_service import run_discovery_and_download
                runner_started = True
                summary = run_discovery_and_download(task_started=True)
                logger.info('Manual trigger discovery complete: %s', summary)
            except Exception as exc:
                if not runner_started:
                    finish_task(error=str(exc))
                logger.error('Manual trigger discovery failed: %s', exc, exc_info=True)

        t = threading.Thread(target=_bg, daemon=True)
        t.start()
        _success_response(self, {
            'started': True,
            'task_id': task['task_id'],
            'status': task['status'],
            'message': 'Discovery + download triggered in background',
        })

    def _handle_post_download(self) -> None:
        """POST /api/download — download a specific YouTube URL.

        Body: {"url": "https://www.youtube.com/watch?v=xxx", "category": "pets"}
        Returns video_id immediately, download runs in background.
        """
        body, error = self._read_json_body()
        if body is not None and not body:
            _error_response(self, 'Empty request body', status=400)
            return
        if error:
            _error_response(self, error, status=400)
            return

        url = str(body.get('url', '') or '').strip()
        if not url:
            _error_response(self, '"url" is required', status=400)
            return

        category = str(body.get('category', 'manual') or 'manual').strip()
        vid = _extract_youtube_video_id(url)
        if not vid:
            _error_response(self, 'Could not extract a valid YouTube video_id from url', status=400)
            return

        self._start_manual_download(
            url=url,
            category=category,
            vid=vid,
            input_data={'url': url, 'category': category, 'video_id': vid},
        )

    def _start_manual_download(
        self,
        *,
        url: str,
        category: str,
        vid: str,
        input_data: dict[str, object],
    ) -> None:
        task = try_start_task('manual_download', input_data=input_data)
        if task is None:
            _error_response(
                self,
                'A background task is already running',
                status=409,
                code='task_running',
                details={'task': get_task_state()},
            )
            return

        def _bg() -> None:
            try:
                from app.download_service import run_manual_download
                run_manual_download(url=url, category=category, video_id=vid)
            except Exception as exc:
                finish_task(summary={'video_id': vid, 'url': url, 'downloaded': False}, error=str(exc))
                logger.error('Manual download task failed before service handled it: %s err=%s', url, exc)

        t = threading.Thread(target=_bg, daemon=True)
        t.start()

        _success_response(self, {
            'started': True,
            'task_id': task['task_id'],
            'status': task['status'],
            'video_id': vid,
            'url': url,
        })

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
    init_task_db(db)
    recovered = recover_interrupted_tasks(db)
    if recovered:
        logger.warning('Recovered %d interrupted task(s) at API startup', recovered)
    logger.info('API server starting on %s:%d (db=%s)', h, p, db)

    server = ThreadingHTTPServer((h, p), _ApiHandler)
    server._db_path = db
    return server
