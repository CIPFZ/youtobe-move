from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import yt_dlp

from app.discovery.models import VideoCandidate
from app.discovery.providers.base import SearchKeyword
from app.discovery.scoring import compute_score_details, should_keep_candidate
from app.settings import settings

logger = logging.getLogger(__name__)


def _parse_upload_date(raw_date: str | None) -> str:
    if not raw_date or len(str(raw_date)) != 8:
        return ""
    try:
        dt = datetime.strptime(str(raw_date), "%Y%m%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return ""


class YtdlpSearchProvider:
    name = "ytdlp"

    def search(
        self,
        *,
        keywords: list[SearchKeyword],
        max_results_per_keyword: int,
        min_views: int,
        min_duration_sec: int,
        max_duration_sec: int,
    ) -> list[VideoCandidate]:
        out: list[VideoCandidate] = []
        result_limit = max(1, min(max_results_per_keyword, 50))

        ytdlp_opts: dict = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "no_warnings": True,
        }
        proxy = settings.ytdlp_proxy.strip()
        if proxy:
            ytdlp_opts["proxy"] = proxy

        logger.info(
            "Discovery (yt-dlp) started. keywords=%d max_results_per_keyword=%d proxy=%s",
            len(keywords), result_limit, proxy or "none",
        )

        for item_kw in keywords:
            kw = item_kw.keyword.strip()
            if not kw:
                continue

            kept = 0
            filtered = 0
            try:
                with yt_dlp.YoutubeDL(ytdlp_opts) as ydl:
                    info = ydl.extract_info(
                        f"ytsearch{result_limit}:{kw}",
                        download=False,
                    )

                entries = info.get("entries") or []
                for item in entries:
                    if not isinstance(item, dict):
                        continue

                    vid = str(item.get("id") or "").strip()
                    if not vid:
                        continue

                    view_count = int(item.get("view_count") or 0)
                    duration_sec = int(item.get("duration") or 0)
                    title = str(item.get("title") or "")
                    channel_title = str(item.get("channel") or item.get("uploader") or "")

                    if not should_keep_candidate(
                        view_count=view_count,
                        duration_sec=duration_sec,
                        min_views=min_views,
                        min_duration_sec=min_duration_sec,
                        max_duration_sec=max_duration_sec,
                        title=title,
                        channel_title=channel_title,
                        title_blocklist=settings.discovery_title_blocklist,
                        channel_allowlist=settings.discovery_channel_allowlist,
                        channel_blocklist=settings.discovery_channel_blocklist,
                    ):
                        filtered += 1
                        continue

                    published_at = _parse_upload_date(item.get("upload_date"))
                    score_details = compute_score_details(
                        view_count=view_count,
                        published_at=published_at,
                        duration_sec=duration_sec,
                        title=title,
                        keyword=kw,
                        channel_title=channel_title,
                    )

                    out.append(
                        VideoCandidate(
                            video_id=vid,
                            url=f"https://www.youtube.com/watch?v={vid}",
                            title=title,
                            channel_title=channel_title,
                            published_at=published_at,
                            duration_sec=duration_sec,
                            view_count=view_count,
                            keyword=kw,
                            category=item_kw.category,
                            score=score_details["score_total"],
                            raw_json=json.dumps(item, ensure_ascii=False, default=str),
                            score_json=json.dumps(score_details, ensure_ascii=False, default=str),
                        )
                    )
                    kept += 1

                logger.info(
                    "Discovery keyword done. keyword=%s category=%s raw=%d kept=%d filtered=%d",
                    kw, item_kw.category or "uncategorised", len(entries), kept, filtered,
                )
            except Exception as exc:
                logger.warning("Discovery keyword failed. keyword=%s err=%s", kw, exc)
                continue

            time.sleep(3)

        logger.info("Discovery (yt-dlp) completed. candidates=%d", len(out))
        return out
