from __future__ import annotations

import json
import logging
import ssl
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.discovery.models import VideoCandidate
from app.discovery.scoring import compute_hot_score, safe_int, should_keep_candidate
from app.settings import settings

logger = logging.getLogger(__name__)

_YOUTUBE_API_BASE = 'https://www.googleapis.com/youtube/v3'


def _http_get_json(url: str) -> dict:
    req = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'hk-server/1.0'})
    retries = max(1, int(settings.discovery_http_retries))
    backoff = max(0.2, float(settings.discovery_http_retry_backoff_sec))
    last_err: Exception | None = None
    for i in range(1, retries + 1):
        try:
            with urlopen(req, timeout=30) as resp:
                payload = resp.read()
            return json.loads(payload.decode('utf-8'))
        except HTTPError as exc:
            last_err = exc
            if exc.code < 500 and exc.code != 429:
                raise
        except (URLError, ssl.SSLError, TimeoutError) as exc:
            last_err = exc
        if i < retries:
            time.sleep(backoff * i)
    if last_err is not None:
        raise last_err
    raise RuntimeError('Unknown http error')


def _iso_after(days_back: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=max(1, days_back))
    return dt.replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _parse_iso8601_duration_to_sec(duration: str) -> int:
    if not duration or not duration.startswith('PT'):
        return 0
    dur = duration[2:]
    hours = minutes = seconds = 0
    num = ''
    for ch in dur:
        if ch.isdigit():
            num += ch
            continue
        if ch == 'H':
            hours = int(num or '0')
        elif ch == 'M':
            minutes = int(num or '0')
        elif ch == 'S':
            seconds = int(num or '0')
        num = ''
    return hours * 3600 + minutes * 60 + seconds


def _search_video_ids(api_key: str, query: str, published_after: str, max_results: int) -> list[str]:
    params = {
        'part': 'id',
        'q': query,
        'type': 'video',
        'order': 'viewCount',
        'publishedAfter': published_after,
        'maxResults': max(1, min(max_results, 50)),
        'key': api_key,
        'regionCode': 'US',
        'relevanceLanguage': 'en',
    }
    url = f'{_YOUTUBE_API_BASE}/search?{urlencode(params)}'
    data = _http_get_json(url)
    ids: list[str] = []
    for item in data.get('items', []):
        vid = ((item.get('id') or {}).get('videoId') or '').strip()
        if vid:
            ids.append(vid)
    return ids


def _videos_details(api_key: str, video_ids: list[str]) -> list[dict]:
    if not video_ids:
        return []
    params = {
        'part': 'snippet,contentDetails,statistics',
        'id': ','.join(video_ids),
        'maxResults': 50,
        'key': api_key,
    }
    url = f'{_YOUTUBE_API_BASE}/videos?{urlencode(params)}'
    data = _http_get_json(url)
    return list(data.get('items', []))


def discover_candidates(
    *,
    api_key: str,
    keywords: list[str],
    days_back: int,
    max_results_per_keyword: int,
    min_views: int,
    min_comments: int,
    min_duration_sec: int,
    max_duration_sec: int,
    kw_meta: dict[str, tuple[str, list[str]]] | None = None,
) -> list[VideoCandidate]:
    """Discover candidates from YouTube.

    If *kw_meta* is provided, it maps normalized keyword to (category, allowed_languages).
    """
    if kw_meta is None:
        kw_meta = {}
    out: list[VideoCandidate] = []
    published_after = _iso_after(days_back)
    logger.info(
        'Discovery started. keywords=%d days_back=%d max_results_per_keyword=%d',
        len(keywords), days_back, max_results_per_keyword,
    )

    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        cat, allowed_langs = kw_meta.get(kw.lower(), ('', []))
        try:
            ids = _search_video_ids(api_key, kw, published_after, max_results_per_keyword)
            if not ids:
                continue
            details = _videos_details(api_key, ids)
            for item in details:
                vid = (item.get('id') or '').strip()
                if not vid:
                    continue
                snippet = item.get('snippet') or {}
                stats = item.get('statistics') or {}
                content = item.get('contentDetails') or {}
                duration_sec = _parse_iso8601_duration_to_sec(str(content.get('duration') or ''))
                lang_hint = str(snippet.get('defaultAudioLanguage') or snippet.get('defaultLanguage') or '')
                view_count = safe_int(stats.get('viewCount'))
                comment_count = safe_int(stats.get('commentCount'))
                like_count = safe_int(stats.get('likeCount'))
                if not should_keep_candidate(
                    view_count=view_count,
                    comment_count=comment_count,
                    duration_sec=duration_sec,
                    language_hint=lang_hint,
                    allowed_languages=allowed_langs,
                    min_views=min_views,
                    min_comments=min_comments,
                    min_duration_sec=min_duration_sec,
                    max_duration_sec=max_duration_sec,
                ):
                    continue
                published_at = str(snippet.get('publishedAt') or '')
                title = str(snippet.get('title') or '')
                description = str(snippet.get('description') or '')
                score = compute_hot_score(view_count, comment_count, published_at)
                out.append(
                    VideoCandidate(
                        video_id=vid,
                        url=f'https://www.youtube.com/watch?v={vid}',
                        title=title,
                        description=description,
                        channel_id=str(snippet.get('channelId') or ''),
                        channel_title=str(snippet.get('channelTitle') or ''),
                        published_at=published_at,
                        language_hint=lang_hint,
                        duration_sec=duration_sec,
                        view_count=view_count,
                        comment_count=comment_count,
                        like_count=like_count,
                        keyword=kw,
                        category=cat,
                        score=score,
                        raw_json=json.dumps(item, ensure_ascii=False),
                    )
                )
        except Exception as exc:
            logger.warning('Discovery keyword failed. keyword=%s err=%s', kw, exc)
            continue
    logger.info('Discovery completed. candidates=%d', len(out))
    return out
