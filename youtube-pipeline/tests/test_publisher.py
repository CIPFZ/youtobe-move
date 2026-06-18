import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import Config
from app.publisher import build_publish_payload


class PublisherTests(unittest.TestCase):
    def test_build_publish_payload_from_download_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_dir = root / "abc123def45"
            data_dir.mkdir()
            (data_dir / "abc123def45_merge.mp4").write_bytes(b"demo")
            (data_dir / "meta.json").write_text(
                json.dumps({"id": "abc123def45", "title": "Original title"}, ensure_ascii=False),
                encoding="utf-8",
            )

            config = object.__new__(Config)
            config.bilibili_account = "mybili"
            config.bilibili_tid = 27
            config.bilibili_tid_options = "27:动画-综合,188:科技"
            config.social_auto_upload_dir = root / "social-auto-upload"

            with patch(
                "app.publisher.generate_chinese_metadata",
                return_value={
                    "title": "中文标题",
                    "description": (
                        "https://www.youtube.com/watch?v=abc123def45\n"
                        "这是正文。\n\n"
                        "原视频链接：https://www.youtube.com/watch?v=abc123def45"
                    ),
                    "tags": ["动画", "测试"],
                },
            ):
                with patch(
                    "app.publisher.select_bilibili_tid",
                    return_value={"tid": 27, "label": "动画-综合", "reason": "分类为动画", "source": "llm"},
                ):
                    payload = build_publish_payload(data_dir, config)

        self.assertEqual(payload["account"], "mybili")
        self.assertEqual(payload["tid"], 27)
        self.assertEqual(payload["tid_selection"]["source"], "llm")
        self.assertEqual(payload["title"], "中文标题")
        self.assertEqual(payload["tags"], ["动画", "测试"])
        self.assertEqual(
            payload["description"],
            "这是正文。\n\n原视频链接：https://www.youtube.com/watch?v=abc123def45",
        )


if __name__ == "__main__":
    unittest.main()
