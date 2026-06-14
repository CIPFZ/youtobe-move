from __future__ import annotations

import json

from app.discovery import service
from app.discovery.models import VideoCandidate
from app.discovery.providers import get_provider
from app.discovery.providers.base import SearchKeyword, UnsupportedProviderError
from app.discovery.providers.ytdlp_search import YtdlpSearchProvider


def test_get_provider_resolves_supported_names():
    assert get_provider("ytdlp").name == "ytdlp"
    assert get_provider("yt-dlp").name == "ytdlp"
    assert get_provider("youtube_api").name == "youtube_api"


def test_get_provider_rejects_unknown_name():
    try:
        get_provider("unknown")
    except UnsupportedProviderError as exc:
        assert "Unsupported discovery provider" in str(exc)
    else:
        raise AssertionError("Unsupported provider did not raise")


def test_ytdlp_provider_maps_and_filters_entries(monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, query, download=False):
            assert query == "ytsearch3:cats"
            assert download is False
            return {
                "entries": [
                    {
                        "id": "abc123def45",
                        "title": "Good cat",
                        "channel": "Cat Channel",
                        "upload_date": "20240601",
                        "duration": 120,
                        "view_count": 20000,
                    },
                    {
                        "id": "lowviews123",
                        "title": "Low views",
                        "duration": 120,
                        "view_count": 1,
                    },
                ]
            }

    monkeypatch.setattr("app.discovery.providers.ytdlp_search.yt_dlp.YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr("app.discovery.providers.ytdlp_search.time.sleep", lambda seconds: None)

    candidates = YtdlpSearchProvider().search(
        keywords=[SearchKeyword(keyword="cats", category="pets")],
        max_results_per_keyword=3,
        min_views=100,
        min_duration_sec=60,
        max_duration_sec=1800,
    )

    assert len(candidates) == 1
    assert candidates[0].video_id == "abc123def45"
    assert candidates[0].category == "pets"
    assert candidates[0].published_at.startswith("2024-06-01")
    assert json.loads(candidates[0].raw_json)["title"] == "Good cat"
    score_json = json.loads(candidates[0].score_json)
    assert score_json["score_total"] == candidates[0].score
    assert "score_views" in score_json


def test_ytdlp_provider_applies_quality_blocklists(monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, query, download=False):
            return {
                "entries": [
                    {
                        "id": "blockedtitl",
                        "title": "Spam trailer",
                        "channel": "Trusted Channel",
                        "duration": 120,
                        "view_count": 20000,
                    },
                    {
                        "id": "blockedchan",
                        "title": "Good video",
                        "channel": "Blocked Channel",
                        "duration": 120,
                        "view_count": 20000,
                    },
                    {
                        "id": "allowedvid1",
                        "title": "Good video",
                        "channel": "Trusted Channel",
                        "duration": 120,
                        "view_count": 20000,
                    },
                ]
            }

    monkeypatch.setattr("app.discovery.providers.ytdlp_search.yt_dlp.YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr("app.discovery.providers.ytdlp_search.time.sleep", lambda seconds: None)
    monkeypatch.setattr("app.discovery.providers.ytdlp_search.settings.discovery_title_blocklist", "trailer")
    monkeypatch.setattr("app.discovery.providers.ytdlp_search.settings.discovery_channel_blocklist", "blocked")
    monkeypatch.setattr("app.discovery.providers.ytdlp_search.settings.discovery_channel_allowlist", "trusted")

    candidates = YtdlpSearchProvider().search(
        keywords=[SearchKeyword(keyword="video", category="funny")],
        max_results_per_keyword=3,
        min_views=100,
        min_duration_sec=60,
        max_duration_sec=1800,
    )

    assert [item.video_id for item in candidates] == ["allowedvid1"]


def test_discovery_preview_uses_configured_provider(monkeypatch):
    class DummyProvider:
        name = "dummy"

        def search(self, **kwargs):
            assert kwargs["max_results_per_keyword"] == 2
            return [
                VideoCandidate(
                    video_id="abc123def45",
                    url="https://youtube.com/watch?v=abc123def45",
                    title="A",
                    channel_title="C",
                    published_at="",
                    duration_sec=100,
                    view_count=1000,
                    keyword="cats",
                    category="pets",
                    score=3.0,
                    raw_json="{}",
                ),
                VideoCandidate(
                    video_id="abc123def46",
                    url="https://youtube.com/watch?v=abc123def46",
                    title="B",
                    channel_title="C",
                    published_at="",
                    duration_sec=100,
                    view_count=2000,
                    keyword="dogs",
                    category="pets",
                    score=8.0,
                    raw_json="{}",
                ),
            ]

    monkeypatch.setattr(service.settings, "discovery_provider", "dummy")
    monkeypatch.setattr(service.settings, "discovery_topic_types", "")
    monkeypatch.setattr(service.settings, "discovery_keywords", "cats,dogs")
    monkeypatch.setattr(service.settings, "discovery_max_results_per_keyword", 2)
    monkeypatch.setattr(service, "get_provider", lambda name: DummyProvider())

    preview = service.discovery_preview(top_n=1)

    assert preview["provider"] == "dummy"
    assert preview["raw_count"] == 2
    assert preview["selected_count"] == 1
    assert preview["items"][0]["video_id"] == "abc123def46"
    assert [item["video_id"] for item in preview["raw_items"]] == ["abc123def45", "abc123def46"]
