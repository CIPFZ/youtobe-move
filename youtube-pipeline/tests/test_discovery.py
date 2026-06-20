import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.discovery.models import DiscoverySource, VideoCandidate
from app.discovery.service import discover_videos, preview_discovery_source
from app.discovery.sources import fetch_candidates_for_source, load_discovery_sources


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pipeline.db"
        self.config = SimpleNamespace(
            db_path=self.db_path,
            discovery_sources_json=json.dumps(
                [
                    {"type": "search", "keyword": "animated short", "max_results": 2},
                    {"type": "trending", "region_code": "US", "max_results": 2},
                ]
            ),
            discovery_max_results_per_source=5,
            discovery_min_duration_seconds=10,
            discovery_max_duration_seconds=600,
            discovery_min_view_count=100,
            discovery_title_blocklist="blocked",
            discovery_channel_allowlist="",
            discovery_channel_blocklist="",
            discovery_category_allowlist="",
            discovery_category_blocklist="",
        )
        self.addCleanup(self.temp_dir.cleanup)

    def _candidate(
        self,
        video_id="abc123def45",
        title="Animated short",
        duration=120,
        view_count=1000,
        source_type="search",
    ):
        return VideoCandidate(
            video_id=video_id,
            source_type=source_type,
            source_name=f"{source_type}:0",
            source_query="animated short",
            title=title,
            channel_id="UCabc",
            channel="Channel",
            duration=duration,
            view_count=view_count,
            published_at="2026-01-01T00:00:00Z",
            category="1",
            score=0.0,
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            raw={},
        )

    def test_load_discovery_sources_filters_by_type(self):
        sources = load_discovery_sources(self.config, source_type="search")

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].type, "search")
        self.assertEqual(sources[0].params["keyword"], "animated short")

    def test_load_discovery_sources_skips_disabled_and_sorts_priority(self):
        self.config.discovery_sources_json = json.dumps(
            [
                {"type": "search", "name": "late", "keyword": "late", "max_results": 1, "priority": 50},
                {"type": "search", "name": "off", "keyword": "off", "max_results": 1, "enabled": False, "priority": 1},
                {"type": "trending", "name": "early", "region_code": "US", "max_results": 1, "priority": 10},
            ]
        )

        sources = load_discovery_sources(self.config)

        self.assertEqual([source.name for source in sources], ["early", "late"])

    def test_discover_dry_run_does_not_insert(self):
        candidates = [self._candidate()]

        with patch("app.discovery.service.fetch_candidates", return_value=candidates):
            result = discover_videos(self.config, dry_run=True)

        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["inserted_count"], 0)
        with connect(self.db_path) as conn:
            init_schema(conn)
            repo = Repository(conn)
            self.assertIsNone(repo.get_video("abc123def45"))

    def test_preview_discovery_source_does_not_insert(self):
        candidates = [
            self._candidate(video_id="abc123def45"),
            self._candidate(video_id="small123456", view_count=99),
        ]

        with patch("app.discovery.service.fetch_candidates_for_source", return_value=candidates):
            result = preview_discovery_source(self.config, 0)

        self.assertEqual(result["source"]["index"], 0)
        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(result["accepted_count"], 1)
        self.assertEqual(result["rejected"][0]["reason"], "view_count_too_low")
        with connect(self.db_path) as conn:
            init_schema(conn)
            repo = Repository(conn)
            self.assertIsNone(repo.get_video("abc123def45"))

    def test_discover_inserts_selected_video_and_download_job(self):
        candidate = self._candidate()
        candidate = VideoCandidate(**{**candidate.__dict__, "source_name": "source-a", "source_params": {"priority": 7}})
        candidates = [candidate]

        with patch("app.discovery.service.fetch_candidates", return_value=candidates):
            result = discover_videos(self.config, dry_run=False)

        self.assertEqual(result["inserted_count"], 1)
        with connect(self.db_path) as conn:
            init_schema(conn)
            repo = Repository(conn)
            video = repo.get_video("abc123def45")
            job = repo.get_latest_job("abc123def45", "download")
            self.assertEqual(video["status"], "selected")
            self.assertEqual(video["title"], "Animated short")
            self.assertEqual(video["priority"], 7)
            self.assertEqual(video["source_label"], "source-a")
            self.assertEqual(job["status"], "pending")

    def test_discover_rejects_duplicate_and_blocked_title(self):
        candidates = [
            self._candidate(video_id="abc123def45"),
            self._candidate(video_id="abc123def45"),
            self._candidate(video_id="blocked1234", title="Blocked trailer"),
        ]

        with patch("app.discovery.service.fetch_candidates", return_value=candidates):
            result = discover_videos(self.config, dry_run=False)

        reasons = [item["reason"] for item in result["rejected"]]
        self.assertEqual(result["inserted_count"], 1)
        self.assertIn("duplicate_in_run", reasons)
        self.assertIn("title_blocked:blocked", reasons)

    def test_discover_rejects_duration_and_view_count(self):
        candidates = [
            self._candidate(video_id="short123456", duration=5),
            self._candidate(video_id="long1234567", duration=601),
            self._candidate(video_id="small123456", view_count=99),
        ]

        with patch("app.discovery.service.fetch_candidates", return_value=candidates):
            result = discover_videos(self.config, dry_run=True)

        reasons = [item["reason"] for item in result["rejected"]]
        self.assertIn("duration_too_short", reasons)
        self.assertIn("duration_too_long", reasons)
        self.assertIn("view_count_too_low", reasons)

    def test_source_level_filter_overrides_global_filter(self):
        candidate = self._candidate(view_count=1000)
        candidate = VideoCandidate(
            **{
                **candidate.__dict__,
                "source_params": {"min_view_count": 2000, "category_allowlist": "1"},
            }
        )

        with patch("app.discovery.service.fetch_candidates", return_value=[candidate]):
            result = discover_videos(self.config, dry_run=True)

        self.assertEqual(result["accepted_count"], 0)
        self.assertEqual(result["rejected"][0]["reason"], "view_count_too_low")

    def test_discover_filters_channel_and_category_rules(self):
        self.config.discovery_channel_blocklist = "UCblocked"
        self.config.discovery_category_allowlist = "1"
        candidates = [
            self._candidate(video_id="blockedchan", title="Channel video"),
            self._candidate(video_id="badcategory", title="Bad category"),
        ]
        candidates[0] = VideoCandidate(**{**candidates[0].__dict__, "channel_id": "UCblocked"})
        candidates[1] = VideoCandidate(**{**candidates[1].__dict__, "category": "22"})

        with patch("app.discovery.service.fetch_candidates", return_value=candidates):
            result = discover_videos(self.config, dry_run=True)

        reasons = [item["reason"] for item in result["rejected"]]
        self.assertIn("channel_blocked:ucblocked", reasons)
        self.assertIn("category_not_allowed", reasons)

    def test_discover_sorts_candidates_by_score(self):
        candidates = [
            self._candidate(video_id="low12345678", view_count=100),
            self._candidate(video_id="high1234567", view_count=1_000_000),
        ]

        with patch("app.discovery.service.fetch_candidates", return_value=candidates):
            result = discover_videos(self.config, dry_run=True)

        self.assertEqual(result["accepted"][0]["video_id"], "high1234567")
        self.assertGreater(result["accepted"][0]["score"], result["accepted"][1]["score"])

    def test_source_score_weight_changes_candidate_order(self):
        low_views = self._candidate(video_id="low12345678", view_count=100)
        high_views = self._candidate(video_id="high1234567", view_count=1_000_000)
        low_views = VideoCandidate(**{**low_views.__dict__, "source_params": {"score_weight": 3.0}})
        high_views = VideoCandidate(**{**high_views.__dict__, "source_params": {"score_weight": 1.0}})

        with patch("app.discovery.service.fetch_candidates", return_value=[low_views, high_views]):
            result = discover_videos(self.config, dry_run=True)

        self.assertEqual(result["accepted"][0]["video_id"], "low12345678")
        self.assertGreater(result["accepted"][0]["score"], result["accepted"][1]["score"])

    def test_channel_uploads_source_accepts_handle(self):
        source = DiscoverySource(
            type="channel_uploads",
            name="channel",
            params={"type": "channel_uploads", "handle": "@demo", "max_results": 1},
        )
        item = {
            "id": "abc123def45",
            "snippet": {"title": "Video", "channelId": "UCdemo", "channelTitle": "Demo"},
            "contentDetails": {"duration": "PT2M"},
            "statistics": {"viewCount": "1000"},
        }

        with (
            patch("app.discovery.sources.get_channel_id_by_handle", return_value="UCdemo") as resolve,
            patch("app.discovery.sources.get_channel_uploads", return_value=[item]) as uploads,
        ):
            candidates = fetch_candidates_for_source(source, self.config)

        resolve.assert_called_once()
        uploads.assert_called_once()
        self.assertEqual(candidates[0].channel_id, "UCdemo")
        self.assertEqual(candidates[0].source_query, "@demo")


if __name__ == "__main__":
    unittest.main()
