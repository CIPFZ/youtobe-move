from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener, urlopen
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import yt_dlp

from app.settings import settings

logger = logging.getLogger(__name__)


def _normalize_youtube_url_for_first_item(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    video_ids = query.get('v')
    if not video_ids:
        return url
    clean_query = urlencode({'v': video_ids[0]})
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, parsed.fragment))


def _build_video_metadata(info: dict[str, Any], source_url: str, normalized_url: str, playlist_strategy: str) -> dict[str, Any]:
    thumbnails = info.get('thumbnails') if isinstance(info.get('thumbnails'), list) else []
    return {
        'id': info.get('id'),
        'title': info.get('title'),
        'fulltitle': info.get('fulltitle'),
        'description': info.get('description'),
        'uploader': info.get('uploader'),
        'uploader_id': info.get('uploader_id'),
        'uploader_url': info.get('uploader_url'),
        'channel': info.get('channel'),
        'channel_id': info.get('channel_id'),
        'channel_url': info.get('channel_url'),
        'upload_date': info.get('upload_date'),
        'release_date': info.get('release_date'),
        'timestamp': info.get('timestamp'),
        'duration': info.get('duration'),
        'duration_string': info.get('duration_string'),
        'view_count': info.get('view_count'),
        'like_count': info.get('like_count'),
        'comment_count': info.get('comment_count'),
        'categories': info.get('categories'),
        'tags': info.get('tags'),
        'age_limit': info.get('age_limit'),
        'language': info.get('language'),
        'live_status': info.get('live_status'),
        'playable_in_embed': info.get('playable_in_embed'),
        'fps': info.get('fps'),
        'vcodec': info.get('vcodec'),
        'acodec': info.get('acodec'),
        'resolution': info.get('resolution'),
        'width': info.get('width'),
        'height': info.get('height'),
        'aspect_ratio': info.get('aspect_ratio'),
        'audio_channels': info.get('audio_channels'),
        'filesize': info.get('filesize'),
        'filesize_approx': info.get('filesize_approx'),
        'ext': info.get('ext'),
        'format': info.get('format'),
        'format_id': info.get('format_id'),
        'format_note': info.get('format_note'),
        'tbr': info.get('tbr'),
        'abr': info.get('abr'),
        'vbr': info.get('vbr'),
        'thumbnails': thumbnails,
        'thumbnail_count': len(thumbnails),
        'webpage_url': info.get('webpage_url'),
        'original_url': info.get('original_url'),
        'extractor_key': info.get('extractor_key'),
        'extractor': info.get('extractor'),
        'source_url': source_url,
        'normalized_url': normalized_url,
        'playlist_strategy': playlist_strategy,
    }


def _ytdlp_opts(out_dir: Path, selector: str, cookie_file: str, proxy_url: str) -> dict[str, Any]:
    opts: dict[str, Any] = {
        'quiet': False,
        'noplaylist': True,
        'outtmpl': str(out_dir / '%(id)s.%(ext)s'),
        'format': selector,
    }
    if cookie_file:
        opts['cookiefile'] = cookie_file
    if proxy_url:
        opts['proxy'] = proxy_url
    return opts


def _selector_candidates(stream_kind: str) -> list[str]:
    primary = settings.ytdlp_video_format if stream_kind == 'video' else settings.ytdlp_audio_format
    if stream_kind == 'video':
        fallback = ['bestvideo[ext=mp4]']
    else:
        fallback = ['bestaudio[ext=m4a]']
    candidates: list[str] = []
    for sel in [primary, *fallback]:
        if sel and sel not in candidates:
            candidates.append(sel)
    return candidates


def _download_stream(normalized_url: str, out_dir: Path, stream_kind: str, cookie_file: str, proxy_url: str) -> tuple[dict[str, Any], Path]:
    last_exc: Exception | None = None
    info: dict[str, Any] | None = None

    for selector in _selector_candidates(stream_kind):
        opts = _ytdlp_opts(out_dir=out_dir, selector=selector, cookie_file=cookie_file, proxy_url=proxy_url)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(normalized_url, download=True)
            break
        except Exception as exc:
            last_exc = exc
            message = str(exc)
            unavailable = 'Requested format is not available' in message
            logger.warning(
                'yt-dlp %s download failed with selector=%s. unavailable=%s err=%s',
                stream_kind, selector, unavailable, message,
            )
            if unavailable:
                continue
            raise

    if info is None:
        raise RuntimeError(
            f'Failed to download {stream_kind}. tried selectors={_selector_candidates(stream_kind)}'
        ) from last_exc

    video_id = info.get('id')
    if not video_id:
        raise RuntimeError('yt-dlp did not return video id.')

    ext = 'mp4' if stream_kind == 'video' else 'm4a'
    target = out_dir / f'{video_id}.{ext}'
    if target.exists():
        return info, target

    same_ext = sorted(out_dir.glob(f'{video_id}.{ext}'))
    if same_ext:
        return info, same_ext[0]

    existing = [p for p in sorted(out_dir.glob(f'{video_id}.*'))
                if not p.name.lower().endswith('.part') and '.thumbnail.' not in p.name and p.is_file()]
    existing_str = ', '.join(str(p) for p in existing) if existing else 'none'
    raise RuntimeError(
        f'{stream_kind} download must be .{ext}, but no .{ext} file exists for id={video_id}. '
        f'found={existing_str}.'
    )


def _thumbnail_sort_key(thumb: dict[str, Any]) -> tuple[int, int, int, int]:
    width = int(thumb.get('width') or 0)
    height = int(thumb.get('height') or 0)
    resolution = width * height
    preference = int(thumb.get('preference') or 0)
    return (resolution, width, height, preference)


def _guess_thumbnail_extension(url: str, fallback: str = 'jpg') -> str:
    parsed = urlparse(url)
    filename = Path(parsed.path).name
    m = re.search(r'\.([a-zA-Z0-9]{2,5})$', filename)
    if not m:
        return fallback
    ext = m.group(1).lower()
    if ext == 'jpeg':
        return 'jpg'
    return ext


def _download_best_thumbnail(info: dict[str, Any], out_dir: Path, proxy_url: str = "") -> tuple[Path | None, dict[str, Any]]:
    thumbnails = info.get('thumbnails') if isinstance(info.get('thumbnails'), list) else []
    valid = [thumb for thumb in thumbnails if isinstance(thumb, dict) and str(thumb.get('url') or '').strip()]
    if not valid:
        return None, {}

    best = max(valid, key=_thumbnail_sort_key)
    thumb_url = str(best.get('url')).strip()
    video_id = str(info.get('id') or 'unknown')
    ext = _guess_thumbnail_extension(thumb_url)
    target = out_dir / f'{video_id}.thumbnail.{ext}'

    req = Request(thumb_url, headers={'User-Agent': 'Mozilla/5.0'})

    try:
        if proxy_url:
            opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
            with opener.open(req, timeout=30) as resp:
                target.write_bytes(resp.read())
        else:
            with urlopen(req, timeout=30) as resp:
                target.write_bytes(resp.read())
    except (URLError, OSError, Exception):
        logger.warning('Best thumbnail download failed. id=%s url=%s', video_id, thumb_url, exc_info=True)
        return None, best

    return target, best


def download_media(
    url: str,
    out_dir: Path,
    cookie_file: str = '',
    proxy_url: str = '',
    playlist_strategy: str = 'first',
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    if playlist_strategy not in {'first'}:
        raise ValueError('playlist_strategy currently supports only: first')

    normalized_url = _normalize_youtube_url_for_first_item(url)

    if normalized_url != url:
        logger.info('Playlist-style URL normalized to first-item URL. from=%s to=%s', url, normalized_url)

    logger.info('yt-dlp start. url=%s proxy=%s output_dir=%s', normalized_url, proxy_url or 'none', out_dir)

    video_info, video_path = _download_stream(normalized_url, out_dir, 'video', cookie_file, proxy_url)
    _audio_info, audio_path = _download_stream(normalized_url, out_dir, 'audio', cookie_file, proxy_url)
    thumbnail_path, thumbnail_meta = _download_best_thumbnail(video_info, out_dir, proxy_url=proxy_url)

    metadata = _build_video_metadata(
        info=video_info,
        source_url=url,
        normalized_url=normalized_url,
        playlist_strategy=playlist_strategy,
    )
    metadata['best_thumbnail'] = thumbnail_meta
    metadata['thumbnail_path'] = str(thumbnail_path) if thumbnail_path else ''

    logger.info(
        'yt-dlp completed. id=%s title=%s video=%s audio=%s thumbnail=%s',
        metadata.get('id'), metadata.get('title'), video_path, audio_path, thumbnail_path or 'none',
    )
    return {
        'title': video_info.get('title', video_info.get('id', 'unknown')),
        'video_path': video_path,
        'audio_path': audio_path,
        'thumbnail_path': thumbnail_path,
        'metadata': metadata,
    }
