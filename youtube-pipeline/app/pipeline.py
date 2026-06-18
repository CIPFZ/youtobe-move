from __future__ import annotations

from app.config import Config
from app.downloader import download_video_assets
from app.publisher import publish_to_bilibili


def run_download_publish(url: str, config: Config, tid: int | None = None, dry_run_publish: bool = False) -> dict:
    download_result = download_video_assets(url, config)
    publish_result = publish_to_bilibili(
        data_dir=config.output_dir / download_result["video_id"],
        config=config,
        tid=tid,
        dry_run=dry_run_publish,
    )
    return {
        "download": download_result,
        "publish": publish_result,
    }
