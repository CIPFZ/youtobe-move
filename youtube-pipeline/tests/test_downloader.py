import unittest
from types import SimpleNamespace

from app.downloader import build_ytdlp_options


class DownloaderTests(unittest.TestCase):
    def test_build_ytdlp_options_sets_remote_components(self):
        config = SimpleNamespace(
            socket_timeout=20,
            retries=3,
            fragment_retries=3,
            retry_backoff_factor=0.5,
            cookie_file="",
            proxy="",
            ytdlp_remote_components="ejs:github,ejs:npm",
        )

        options = build_ytdlp_options(config)

        self.assertEqual(options["remote_components"], ["ejs:github", "ejs:npm"])

    def test_build_ytdlp_options_omits_empty_remote_components(self):
        config = SimpleNamespace(
            socket_timeout=20,
            retries=3,
            fragment_retries=3,
            retry_backoff_factor=0.5,
            cookie_file="",
            proxy="",
            ytdlp_remote_components="",
        )

        options = build_ytdlp_options(config)

        self.assertNotIn("remote_components", options)


if __name__ == "__main__":
    unittest.main()
