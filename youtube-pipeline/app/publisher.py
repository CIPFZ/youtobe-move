from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from app.ai_describe import generate_chinese_metadata, normalize_source_description, select_bilibili_tid
from app.config import Config


logger = logging.getLogger("youtube-pipeline")


def read_meta(data_dir: Path) -> dict[str, Any]:
    import json

    meta_path = data_dir / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"meta.json is missing: {meta_path}")
    return json.loads(meta_path.read_text(encoding="utf-8"))


def resolve_video_id(meta: dict[str, Any], data_dir: Path) -> str:
    return str(meta.get("id") or data_dir.name).strip()


def resolve_merged_file(data_dir: Path, video_id: str) -> Path:
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


def normalize_title(title: str) -> str:
    return " ".join(title.split())[:80]


def normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        parsed = [item.strip() for item in tags.replace("，", ",").split(",") if item.strip()]
    elif isinstance(tags, list):
        parsed = [str(item).strip() for item in tags if str(item).strip()]
    else:
        parsed = []
    return parsed[:8]


def build_publish_payload(data_dir: Path, config: Config, tid: int | None = None) -> dict[str, Any]:
    data_dir = data_dir.expanduser().resolve()
    meta = read_meta(data_dir)
    video_id = resolve_video_id(meta, data_dir)
    merged_file = resolve_merged_file(data_dir, video_id)
    generated = generate_chinese_metadata(meta, config)

    youtube_url = str(meta.get("webpage_url") or meta.get("original_url") or f"https://www.youtube.com/watch?v={video_id}")
    description = normalize_source_description(str(generated.get("description") or ""), youtube_url)
    if tid is None:
        tid_selection = select_bilibili_tid(meta, config)
        selected_tid = int(tid_selection["tid"])
    else:
        selected_tid = tid
        tid_selection = {
            "tid": tid,
            "label": "",
            "reason": "manual --tid override",
            "source": "manual",
        }
    return {
        "account": config.bilibili_account,
        "video_file": str(merged_file),
        "title": normalize_title(str(generated.get("title") or meta.get("title") or video_id)),
        "description": description,
        "tid": selected_tid,
        "tid_selection": tid_selection,
        "tags": normalize_tags(generated.get("tags")),
    }


def _load_social_upload_module(config: Config):
    social_dir = config.social_auto_upload_dir.expanduser().resolve()
    hk_puller_path = social_dir / "hk_puller.py"
    if not hk_puller_path.exists():
        raise FileNotFoundError(f"social-auto-upload hk_puller.py is missing: {hk_puller_path}")
    if str(social_dir) not in sys.path:
        sys.path.insert(0, str(social_dir))

    spec = importlib.util.spec_from_file_location("youtube_pipeline_social_hk_puller", hk_puller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load social-auto-upload publisher from {hk_puller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def publish_to_bilibili(data_dir: Path, config: Config, tid: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    payload = build_publish_payload(data_dir, config, tid)
    payload["dry_run"] = dry_run
    if dry_run:
        return payload

    module = _load_social_upload_module(config)
    module.upload_to_bilibili(
        video_path=Path(payload["video_file"]),
        title=payload["title"],
        description=payload["description"],
        tid=int(payload["tid"]),
        tags=payload["tags"],
        account=payload["account"],
    )
    logger.info("Published to Bilibili: file=%s tid=%s", payload["video_file"], payload["tid"])
    return payload
