from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import yt_dlp

from app.discovery.models import VideoCandidate
from app.discovery.scoring import compute_hot_score, should_keep_candidate
from app.settings import settings

logger = logging.getLogger(__name__)


def _parse_upload_date(raw_date: str | None) -> str:
    """Convert yt-dlp upload_date (YYYYMMDD) to ISO8601 string.
    If parsing fails, return empty string.
    """
    if not raw_date or len(str(raw_date)) != 8:
        return ''
    try:
        dt = datetime.strptime(str(raw_date), '%Y%m%d').replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return ''


def _discover_candidates_ytdlp(
    api_key: str,  # kept for signature compat, unused
    keywords: list[str],
    days_back: int,
    max_results_per_keyword: int,
    min_views: int,
    min_comments: int,
    min_duration_sec: int,
    max_duration_sec: int,
    kw_meta: dict[str, tuple[str, list[str]]] | None = None,
) -> list[VideoCandidate]:
    """Discover candidates using yt-dlp's built-in YouTube search.

    Uses ``ytsearchN:keyword`` which scrapes YouTube web search — zero API quota.
    """
    if kw_meta is None:
        kw_meta = {}

    out: list[VideoCandidate] = []
    result_limit = max(1, min(max_results_per_keyword, 50))

    ytdlp_opts: dict = {
        'quiet': True,
        'extract_flat': 'in_playlist',
        'no_warnings': True,
    }
    proxy = settings.ytdlp_proxy.strip()
    if proxy:
        ytdlp_opts['proxy'] = proxy

    logger.info(
        'Discovery (yt-dlp) started. keywords=%d max_results_per_keyword=%d proxy=%s',
        len(keywords), result_limit, proxy or 'none',
    )

    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue

        cat, allowed_langs = kw_meta.get(kw.lower(), ('', []))

        try:
            with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
                info = ydl.extract_info(
                    f'ytsearch{result_limit}:{kw}',
                    download=False,
                )

            entries = info.get('entries') or []
            for item in entries:
                if not isinstance(item, dict):
                    continue

                vid = str(item.get('id') or '').strip()
                if not vid:
                    continue

                view_count = int(item.get('view_count') or 0)
                comment_count = 0  # yt-dlp flat search doesn't provide this
                duration_sec = int(item.get('duration') or 0)

                # yt-dlp flat search doesn't give language — check against empty list passes all
                lang_hint = ''

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

                raw_date = item.get('upload_date')
                published_at = _parse_upload_date(raw_date)

                title = str(item.get('title') or '')
                description = str(item.get('description') or '')

                score = compute_hot_score(view_count, comment_count, published_at)

                out.append(
                    VideoCandidate(
                        video_id=vid,
                        url=f'https://www.youtube.com/watch?v={vid}',
                        title=title,
                        description=description,
                        channel_id=str(item.get('channel_id') or item.get('uploader_id') or ''),
                        channel_title=str(item.get('channel') or item.get('uploader') or ''),
                        published_at=published_at,
                        language_hint=lang_hint,
                        duration_sec=duration_sec,
                        view_count=view_count,
                        comment_count=comment_count,
                        like_count=0,
                        keyword=kw,
                        category=cat,
                        score=score,
                        raw_json=json.dumps(item, ensure_ascii=False, default=str),
                    )
                )

        except Exception as exc:
            logger.warning('Discovery keyword failed. keyword=%s err=%s', kw, exc)
            continue

        # delay between keywords to be gentle with YouTube scraping
        time.sleep(3)

    logger.info('Discovery (yt-dlp) completed. candidates=%d', len(out))
    return out


# ── public entry point (delegates to yt-dlp impl) ──

discover_candidates = _discover_candidates_ytdlp
