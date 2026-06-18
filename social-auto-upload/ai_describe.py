"""AI-powered video metadata to Chinese description generator.

Uses MiniMax Anthropic-compatible API to translate and summarize YouTube
video metadata into publication-ready Chinese title, description and tags.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def _load_local_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_local_env()


AI_BASE_URL = os.getenv("MINIMAX_ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic").rstrip("/")
AI_API_KEY = os.getenv("MINIMAX_ANTHROPIC_API_KEY", "")
AI_MODEL = os.getenv("MINIMAX_ANTHROPIC_MODEL", "MiniMax-M3")
AI_ANTHROPIC_VERSION = os.getenv("MINIMAX_ANTHROPIC_VERSION", "2023-06-01")
AI_REQUEST_TIMEOUT = int(os.getenv("MINIMAX_REQUEST_TIMEOUT", "60"))
AI_MAX_TOKENS = int(os.getenv("MINIMAX_MAX_TOKENS", "800"))

SYSTEM_PROMPT = """你是一个专业的视频内容运营专家，负责将 YouTube 视频搬到 Bilibili 平台。
你的任务是根据视频的元信息，生成中文的发布内容。

要求：
1. 标题：中文，吸引人但不标题党，保留原意，20-50字
2. 描述：中文自然段落（不是翻译），概括视频内容和亮点，2-4句话，50-200字。末尾须包含 YouTube 原视频链接
3. 标签：5-8个中文标签，用中文逗号分隔

只能输出下面三行，不要编号，不要 Markdown，不要额外解释：
标题：...
描述：...
标签：标签1，标签2，标签3"""


def normalize_source_description(description: str, original_url: str) -> str:
    """Keep body text first and append exactly one source link at the end."""
    description = (description or "").strip()
    if not original_url:
        return description

    source_line_pattern = re.compile(
        rf"^\s*(?:YouTube)?原视频(?:链接)?[：:]\s*{re.escape(original_url)}\s*$",
        re.MULTILINE,
    )
    description = source_line_pattern.sub("", description)
    description = description.replace(original_url, "")
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    if description:
        return f"{description}\n\n原视频链接：{original_url}"
    return f"原视频链接：{original_url}"


def _call_ai(messages: list[dict], max_tokens: int = AI_MAX_TOKENS) -> str:
    """Call MiniMax Anthropic-compatible API."""
    if not AI_API_KEY:
        raise RuntimeError("MINIMAX_ANTHROPIC_API_KEY is not configured")

    resp = requests.post(
        f"{AI_BASE_URL}/v1/messages",
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
            "anthropic-version": AI_ANTHROPIC_VERSION,
        },
        json={
            "model": AI_MODEL,
            "max_tokens": max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        },
        timeout=AI_REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    # Anthropic format: content is list of blocks
    content = data.get("content", [])
    text_parts = []
    for block in content:
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    return "".join(text_parts)


def _parse_metadata_text(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {"title": "", "description": "", "tags": []}
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if line.startswith("标题：") or line.startswith("标题:"):
            result["title"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif line.startswith("描述：") or line.startswith("描述:"):
            result["description"] = line.split("：", 1)[-1].split(":", 1)[-1].strip()
        elif line.startswith("标签：") or line.startswith("标签:"):
            raw_tags = line.split("：", 1)[-1].split(":", 1)[-1]
            tags = raw_tags.replace(",", "，").split("，")
            result["tags"] = [tag.strip().lstrip("#") for tag in tags if tag.strip()]
    if not result["title"] or not result["description"]:
        raise ValueError(f"AI response does not match metadata format: {text[:200]}")
    return result


def generate_chinese_metadata(meta: dict[str, Any], category: str = "") -> dict[str, Any]:
    """Generate Chinese title, description and tags from video metadata.

    Args:
        meta: Full .video_info.json content from yt-dlp.
        category: Category label like 'pets', 'beauty', 'funny'.

    Returns:
        {"title": "...", "description": "...", "tags": [...]}
    """
    # Prepare structured input about the video
    video_id = meta.get("id", "")
    original_url = f"https://www.youtube.com/watch?v={video_id}"

    video_info = {
        "标题": meta.get("title", meta.get("fulltitle", "")),
        "频道": meta.get("channel", meta.get("uploader", "")),
        "时长": meta.get("duration_string", f'{meta.get("duration", 0)}秒'),
        "播放量": f"{meta.get('view_count', 0):,}",
        "点赞数": f"{meta.get('like_count', 0):,}",
        "标签": meta.get("tags", [])[:10],
        "分类": meta.get("categories", []),
        "分辨率": meta.get("resolution", ""),
        "YouTube链接": original_url,
    }

    # Build description if available
    original_desc = meta.get("description", "")
    if original_desc:
        video_info["原始描述"] = original_desc[:500]

    user_msg = "\n".join(f"{key}: {value}" for key, value in video_info.items())
    prompt = f"请根据以下视频信息生成中文发布内容：\n\n{user_msg}"

    try:
        raw = _call_ai([
            {"role": "user", "content": prompt},
        ])
        result = _parse_metadata_text(raw)

        result["description"] = normalize_source_description(result.get("description", ""), original_url)

        logger.info("AI generated Chinese metadata for %s", video_id)
        return result

    except Exception as exc:
        logger.warning("AI metadata generation failed: %s, using fallback", exc)
        # Fallback: use original info
        original_title = meta.get("title", "") or meta.get("fulltitle", "") or video_id
        channel = meta.get("channel", meta.get("uploader", "N/A"))
        title = f"{original_title} | 中文搬运"[:80]
        desc = (
            f"本视频搬运自 YouTube 频道 {channel}，内容标题为《{original_title}》。"
            f"后续会继续补充更完整的中文介绍。\n\n"
            f"频道: {channel}"
        )
        return {
            "title": title,
            "description": normalize_source_description(desc, original_url),
            "tags": ["YouTube搬运", "视频分享", *meta.get("tags", [])[:6]],
        }
