import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hk_puller


class HkPullerPublishTests(unittest.TestCase):
    def _prepare_db(self, base_dir: Path) -> None:
        db_dir = base_dir / "db"
        db_dir.mkdir(parents=True)
        conn = sqlite3.connect(db_dir / "database.db")
        conn.execute(
            """
            CREATE TABLE hk_videos (
                video_id TEXT PRIMARY KEY,
                upload_status TEXT DEFAULT 'pending',
                uploaded_at TEXT DEFAULT '',
                upload_platform TEXT DEFAULT '',
                upload_account TEXT DEFAULT '',
                error TEXT DEFAULT '',
                thumbnail_path TEXT DEFAULT '',
                meta_path TEXT DEFAULT ''
            )
            """
        )
        conn.execute("INSERT INTO hk_videos (video_id) VALUES ('abc123def45')")
        conn.commit()
        conn.close()

    def test_mark_uploaded_updates_local_db_and_callbacks_hk(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            self._prepare_db(base_dir)

            with patch.object(hk_puller, "BASE_DIR", base_dir):
                with patch.object(hk_puller, "mark_hk_video_published", return_value=True) as callback:
                    ok = hk_puller.mark_uploaded("abc123def45", "bilibili", "creator")

            self.assertTrue(ok)
            callback.assert_called_once_with("abc123def45", platform="bilibili", publish_ref="creator")
            conn = sqlite3.connect(base_dir / "db" / "database.db")
            row = conn.execute(
                "SELECT upload_status, upload_platform, upload_account FROM hk_videos WHERE video_id='abc123def45'"
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("uploaded", "bilibili", "creator"))

    def test_mark_uploaded_keeps_local_success_when_hk_callback_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            self._prepare_db(base_dir)

            with patch.object(hk_puller, "BASE_DIR", base_dir):
                with patch.object(hk_puller, "mark_hk_video_published", side_effect=RuntimeError("offline")):
                    ok = hk_puller.mark_uploaded("abc123def45", "bilibili", "")

            self.assertTrue(ok)
            conn = sqlite3.connect(base_dir / "db" / "database.db")
            row = conn.execute(
                "SELECT upload_status, upload_platform FROM hk_videos WHERE video_id='abc123def45'"
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("uploaded", "bilibili"))

    def test_mark_uploaded_returns_false_for_unknown_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            self._prepare_db(base_dir)

            with patch.object(hk_puller, "BASE_DIR", base_dir):
                with patch.object(hk_puller, "mark_hk_video_published") as callback:
                    ok = hk_puller.mark_uploaded("missingvid00", "bilibili", "")

            self.assertFalse(ok)
            callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()

