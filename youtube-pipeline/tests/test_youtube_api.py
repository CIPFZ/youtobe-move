import unittest

from app.youtube_api import parse_youtube_duration_seconds


class YoutubeApiTests(unittest.TestCase):
    def test_parse_youtube_duration_seconds(self):
        self.assertEqual(parse_youtube_duration_seconds("PT3M25S"), 205)
        self.assertEqual(parse_youtube_duration_seconds("PT1H2M3S"), 3723)
        self.assertEqual(parse_youtube_duration_seconds("P1DT2H"), 93600)
        self.assertIsNone(parse_youtube_duration_seconds("bad"))


if __name__ == "__main__":
    unittest.main()
