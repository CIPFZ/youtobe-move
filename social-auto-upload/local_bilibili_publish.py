"""Publish a locally downloaded YouTube video to Bilibili.

This script bridges the new local hk-server downloader output with the
existing social-auto-upload Bilibili CLI.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from ai_describe import generate_chinese_metadata, normalize_source_description

LOGGER = logging.getLogger("local_bilibili_publish")
DEFAULT_ACCOUNT = "mybili"
DEFAULT_TID = 174


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _resolve_video_id(meta: dict[str, Any], data_dir: Path) -> str:
    video_id = str(meta.get("id") or "").strip()
    if video_id:
        return video_id
    return data_dir.name


def _resolve_merge_file(data_dir: Path, video_id: str) -> Path:
    preferred = data_dir / f"{video_id}_merge.mp4"
    if preferred.exists():
        return preferred
    candidates = sorted(data_dir.glob("*_merge.mp4"))
    if candidates:
        return candidates[0]
    legacy = data_dir / "merged.mp4"
    if legacy.exists():
        return legacy
    raise FileNotFoundError(f"merged video is missing in {data_dir}")


def _normalize_title(title: str) -> str:
    title = " ".join(title.split())
    return title[:80]


def _normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        parsed = [item.strip() for item in tags.split(",") if item.strip()]
    elif isinstance(tags, list):
        parsed = [str(item).strip() for item in tags if str(item).strip()]
    else:
        parsed = []
    return parsed[:8]


def publish_local_bilibili(
    data_dir: Path,
    account: str,
    tid: int,
    dry_run: bool,
) -> dict[str, Any]:
    data_dir = data_dir.expanduser().resolve()
    meta_path = data_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"meta.json is missing: {meta_path}")

    meta = _read_json(meta_path)
    video_id = _resolve_video_id(meta, data_dir)
    merged_file = _resolve_merge_file(data_dir, video_id)
    generated = generate_chinese_metadata(meta)

    title = _normalize_title(str(generated.get("title") or meta.get("title") or video_id))
    description = str(generated.get("description") or "")
    youtube_url = f"https://www.youtube.com/watch?v={video_id}"
    description = normalize_source_description(description, youtube_url)
    tags = _normalize_tags(generated.get("tags"))

    payload = {
        "account": account,
        "video_file": str(merged_file),
        "title": title,
        "description": description,
        "tid": tid,
        "tags": tags,
        "dry_run": dry_run,
    }
    if dry_run:
        return payload

    from hk_puller import upload_to_bilibili

    upload_to_bilibili(
        video_path=merged_file,
        title=title,
        description=description,
        tid=tid,
        tags=tags,
        account=account,
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish local hk-server output to Bilibili.")
    parser.add_argument("data_dir", type=Path, help="Directory containing meta.json and <id>_merge.mp4")
    parser.add_argument("--account", default=DEFAULT_ACCOUNT, help="Bilibili account name")
    parser.add_argument("--tid", default=DEFAULT_TID, type=int, help="Bilibili category id")
    parser.add_argument("--dry-run", action="store_true", help="Generate publish payload without uploading")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args()
    payload = publish_local_bilibili(args.data_dir, args.account, args.tid, args.dry_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
