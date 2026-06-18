import unittest

from app.ai_describe import _parse_metadata_text, normalize_source_description


class AiDescribeTests(unittest.TestCase):
    def test_parse_description_keeps_https_url_colon(self):
        parsed = _parse_metadata_text(
            "\n".join(
                [
                    "标题：示例标题",
                    "描述：https://www.youtube.com/watch?v=dBv8bIZoaBc",
                    "标签：动画，测试",
                ]
            )
        )

        self.assertEqual(parsed["description"], "https://www.youtube.com/watch?v=dBv8bIZoaBc")

    def test_normalize_removes_url_only_body_and_appends_source_line(self):
        description = normalize_source_description(
            "https://www.youtube.com/watch?v=dBv8bIZoaBc",
            "https://www.youtube.com/watch?v=dBv8bIZoaBc",
        )

        self.assertEqual(description, "原视频链接：https://www.youtube.com/watch?v=dBv8bIZoaBc")

    def test_normalize_removes_dangling_source_label(self):
        description = normalize_source_description(
            "这是正文。YouTube原视频链接：\n\nhttps://www.youtube.com/watch?v=dBv8bIZoaBc",
            "https://www.youtube.com/watch?v=dBv8bIZoaBc",
        )

        self.assertEqual(description, "这是正文。\n\n原视频链接：https://www.youtube.com/watch?v=dBv8bIZoaBc")


if __name__ == "__main__":
    unittest.main()
