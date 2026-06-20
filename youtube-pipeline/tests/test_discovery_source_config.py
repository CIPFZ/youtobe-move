import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values

from app.discovery.source_config import (
    add_discovery_source,
    delete_discovery_source,
    list_discovery_source_configs,
    normalize_discovery_source,
    update_discovery_source,
)


class DiscoverySourceConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.db_path = self.base_dir / "pipeline.db"
        self.sources = [
            {"type": "search", "name": "shorts", "keyword": "animated short", "max_results": 2},
            {"type": "trending", "name": "trend", "region_code": "US", "max_results": 3},
        ]
        (self.base_dir / ".env").write_text(
            "\n".join(
                [
                    f"DB_PATH={self.db_path}",
                    f"DISCOVERY_SOURCES_JSON={json.dumps(self.sources, ensure_ascii=False, separators=(',', ':'))}",
                ]
            ),
            encoding="utf-8",
        )
        self.config = SimpleNamespace(
            base_dir=self.base_dir,
            discovery_sources_json=json.dumps(self.sources, ensure_ascii=False),
        )
        self.addCleanup(self.temp_dir.cleanup)

    def _env_sources(self):
        raw = dotenv_values(self.base_dir / ".env")["DISCOVERY_SOURCES_JSON"]
        return json.loads(raw)

    def test_normalize_requires_type_specific_fields(self):
        with self.assertRaises(ValueError):
            normalize_discovery_source({"type": "search", "max_results": 2})
        with self.assertRaises(ValueError):
            normalize_discovery_source({"type": "channel_uploads", "max_results": 2})

        source = normalize_discovery_source({"type": "channel_uploads", "handle": "demo", "max_results": 2})

        self.assertEqual(source["handle"], "@demo")
        self.assertTrue(source["enabled"])
        self.assertEqual(source["priority"], 100)

    def test_normalize_keeps_source_filter_overrides(self):
        source = normalize_discovery_source(
            {
                "type": "search",
                "keyword": "demo",
                "max_results": 2,
                "min_duration_seconds": "30",
                "max_duration_seconds": "300",
                "min_view_count": "2000",
                "title_blocklist": "trailer",
                "category_allowlist": "1,22",
            }
        )

        self.assertEqual(source["min_duration_seconds"], 30)
        self.assertEqual(source["max_duration_seconds"], 300)
        self.assertEqual(source["min_view_count"], 2000)
        self.assertEqual(source["title_blocklist"], "trailer")
        self.assertEqual(source["category_allowlist"], "1,22")

    def test_list_discovery_sources_adds_index(self):
        result = list_discovery_source_configs(self.config)

        self.assertEqual(result["sources"][0]["index"], 0)
        self.assertEqual(result["sources"][1]["type"], "trending")

    def test_add_update_delete_discovery_source_writes_env(self):
        add_discovery_source(
            self.config,
            {"type": "channel_uploads", "name": "channel", "handle": "@demo", "max_results": 1},
        )
        sources = self._env_sources()
        self.assertEqual(len(sources), 3)
        self.assertEqual(sources[2]["handle"], "@demo")

        self.config.discovery_sources_json = json.dumps(sources, ensure_ascii=False)
        update_discovery_source(
            self.config,
            0,
            {"type": "search", "name": "updated", "keyword": "cgi short", "max_results": 4},
        )
        sources = self._env_sources()
        self.assertEqual(sources[0]["keyword"], "cgi short")
        self.assertEqual(sources[0]["max_results"], 4)

        self.config.discovery_sources_json = json.dumps(sources, ensure_ascii=False)
        result = delete_discovery_source(self.config, 1)
        sources = self._env_sources()
        self.assertEqual(result["deleted"]["type"], "trending")
        self.assertEqual(len(sources), 2)


if __name__ == "__main__":
    unittest.main()
