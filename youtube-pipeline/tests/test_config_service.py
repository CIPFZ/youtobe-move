import tempfile
import unittest
from pathlib import Path

from app.config_service import MASKED_VALUE, list_config, update_config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema


class ConfigServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        (self.base_dir / ".env").write_text(
            "\n".join(
                [
                    "DB_PATH=runtime/data/pipeline.db",
                    "PIPELINE_ENABLED=true",
                    "WORKER_INTERVAL_SECONDS=300",
                    "WORKER_ENABLE_DOWNLOAD=true",
                    "PUBLISH_MODE=manual",
                    "YOUTUBE_API_KEY=secret-key",
                    "DISCOVERY_SOURCES_JSON=[]",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        self.addCleanup(self.temp_dir.cleanup)

    def test_list_config_groups_and_masks_sensitive_values(self):
        result = list_config(self.base_dir)

        youtube = {item["key"]: item for item in result["groups"]["youtube"]}
        pipeline = {item["key"]: item for item in result["groups"]["pipeline"]}
        self.assertEqual(youtube["YOUTUBE_API_KEY"]["value"], MASKED_VALUE)
        self.assertTrue(youtube["YOUTUBE_API_KEY"]["sensitive"])
        self.assertIs(pipeline["PIPELINE_ENABLED"]["value"], True)

    def test_update_config_validates_writes_env_and_audit_event(self):
        result = update_config(
            {
                "PIPELINE_ENABLED": False,
                "WORKER_INTERVAL_SECONDS": 120,
                "PUBLISH_MODE": "approved_auto",
            },
            self.base_dir,
            actor="test",
        )

        env_text = (self.base_dir / ".env").read_text(encoding="utf-8")
        self.assertIn("PIPELINE_ENABLED=false", env_text)
        self.assertIn("WORKER_INTERVAL_SECONDS=120", env_text)
        self.assertIn("PUBLISH_MODE=approved_auto", env_text)
        self.assertEqual(result["updated"], ["PIPELINE_ENABLED", "PUBLISH_MODE", "WORKER_INTERVAL_SECONDS"])

        with connect(self.base_dir / "runtime/data/pipeline.db") as conn:
            init_schema(conn)
            repo = Repository(conn)
            events = repo.list_events(limit=1)
        self.assertEqual(events[0]["event_type"], "config_updated")

    def test_update_config_rejects_unknown_and_invalid_values(self):
        with self.assertRaises(ValueError):
            update_config({"UNKNOWN_KEY": "x"}, self.base_dir)
        with self.assertRaises(ValueError):
            update_config({"PUBLISH_MODE": "unsafe"}, self.base_dir)
        with self.assertRaises(ValueError):
            update_config({"WORKER_INTERVAL_SECONDS": 0}, self.base_dir)

    def test_update_config_rejects_masked_sensitive_value(self):
        with self.assertRaises(ValueError):
            update_config({"YOUTUBE_API_KEY": MASKED_VALUE}, self.base_dir)


if __name__ == "__main__":
    unittest.main()
