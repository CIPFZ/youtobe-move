import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_bilibili_publish


class LocalBilibiliPublishTests(unittest.TestCase):
    def test_dry_run_builds_payload_from_meta_and_merge_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "abc123def45"
            data_dir.mkdir()
            (data_dir / "abc123def45_merge.mp4").write_bytes(b"demo")
            (data_dir / "meta.json").write_text(
                json.dumps({"id": "abc123def45", "title": "Original title"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(
                local_bilibili_publish,
                "generate_chinese_metadata",
                return_value={"title": "中文标题", "description": "中文描述", "tags": ["科技", "测试"]},
            ):
                payload = local_bilibili_publish.publish_local_bilibili(
                    data_dir=data_dir,
                    account="mybili",
                    tid=174,
                    dry_run=True,
                )

        self.assertEqual(payload["title"], "中文标题")
        self.assertEqual(payload["tags"], ["科技", "测试"])
        self.assertIn("https://www.youtube.com/watch?v=abc123def45", payload["description"])
        self.assertTrue(payload["dry_run"])

    def test_dry_run_moves_source_link_to_description_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "abc123def45"
            data_dir.mkdir()
            (data_dir / "abc123def45_merge.mp4").write_bytes(b"demo")
            (data_dir / "meta.json").write_text(
                json.dumps({"id": "abc123def45", "title": "Original title"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(
                local_bilibili_publish,
                "generate_chinese_metadata",
                return_value={
                    "title": "中文标题",
                    "description": (
                        "https://www.youtube.com/watch?v=abc123def45\n"
                        "这是正文。\n\n"
                        "原视频链接：https://www.youtube.com/watch?v=abc123def45"
                    ),
                    "tags": ["科技", "测试"],
                },
            ):
                payload = local_bilibili_publish.publish_local_bilibili(
                    data_dir=data_dir,
                    account="mybili",
                    tid=174,
                    dry_run=True,
                )

        self.assertEqual(
            payload["description"],
            "这是正文。\n\n原视频链接：https://www.youtube.com/watch?v=abc123def45",
        )


if __name__ == "__main__":
    unittest.main()
