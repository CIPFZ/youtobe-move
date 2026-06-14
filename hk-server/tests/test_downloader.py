from app import downloader


def test_download_media_maps_stream_progress(monkeypatch, tmp_path):
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def extract_info(self, url, download=True):
            is_audio = "audio" in self.opts["format"]
            ext = "m4a" if is_audio else "mp4"
            target = tmp_path / f"vid12345678.{ext}"
            target.write_bytes(b"data")
            for hook in self.opts.get("progress_hooks", []):
                hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "filename": str(target)})
                hook({"status": "finished", "downloaded_bytes": 100, "total_bytes": 100, "filename": str(target)})
            return {
                "id": "vid12345678",
                "title": "demo",
                "ext": ext,
                "thumbnails": [],
            }

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(downloader, "_download_best_thumbnail", lambda info, out_dir, proxy_url="": (None, {}))

    seen = []
    result = downloader.download_media(
        "https://youtube.com/watch?v=vid12345678",
        tmp_path,
        progress_callback=seen.append,
    )

    assert result["video_path"].name == "vid12345678.mp4"
    assert result["audio_path"].name == "vid12345678.m4a"
    assert [item["progress"] for item in seen] == [25.0, 50.0, 72.5, 95.0, 100.0]
    assert [item["stream"] for item in seen] == ["video", "video", "audio", "audio", "metadata"]
