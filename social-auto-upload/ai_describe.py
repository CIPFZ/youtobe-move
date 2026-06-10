"""AI-powered video metadata to Chinese description generator.

Uses MiniMax Anthropic-compatible API to translate and summarize YouTube
video metadata into publication-ready Chinese title, description and tags.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

# MiniMax Anthropic-compatible endpoint
AI_BASE_URL = "https://api.minimaxi.com/anthropic"
AI_API_KEY = "sk-cp-OR7pwhtJGzK99y6OZj7a18vCu_AtzmdQr-jSRTnFP0RdlJo9q2xYkQ3To6wvwaN22apbesZO8uu99jS7RomD_0NpkT4LkM2Fr0E--p5PS6VCMX4TVLiDJc0"
AI_MODEL = "MiniMax-M1"

SYSTEM_PROMPT = """你是一个专业的视频内容运营专家，负责将 YouTube 视频搬到 Bilibili 平台。
你的任务是根据视频的元信息，生成中文的发布内容。

要求：
1. 标题：中文，吸引人但不标题党，保留原意，20-50字
2. 描述：中文自然段落（不是翻译），概括视频内容和亮点，2-4句话，50-200字。末尾须包含 YouTube 原视频链接
3. 标签：5-8个中文标签，数组格式

输出严格的 JSON 格式，不要任何额外文本：
{"title": "...", "description": "...", "tags": ["...", "..."]}"""


def _call_ai(messages: list[dict], max_tokens: int = 800) -> str:
    """Call MiniMax Anthropic-compatible API."""
    resp = requests.post(
        f"{AI_BASE_URL}/v1/messages",
        headers={
            "Authorization": f"Bearer {AI_API_KEY}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": AI_MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        },
        timeout=60,
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


def _extract_json(text: str) -> dict:
    """Extract JSON from AI response, stripping markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        text = "\n".join(lines[1:-1] if len(lines) > 2 else lines[1:])
    return json.loads(text)


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

    user_msg = json.dumps(video_info, ensure_ascii=False, indent=2)
    prompt = f"请根据以下视频信息生成中文发布内容：\n\n{user_msg}"

    try:
        raw = _call_ai([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])
        result = _extract_json(raw)

        # Ensure the YouTube link is in the description
        desc = result.get("description", "")
        if original_url not in desc:
            desc = f"{desc}\n\n原视频: {original_url}"
        result["description"] = desc

        logger.info("AI generated Chinese metadata for %s", video_id)
        return result

    except Exception as exc:
        logger.warning("AI metadata generation failed: %s, using fallback", exc)
        # Fallback: use original info
        title = meta.get("title", "")[:80]
        desc = (
            f"{meta.get('description', '')[:500]}\n\n"
            f"原视频: {original_url}\n"
            f"频道: {meta.get('channel', meta.get('uploader', 'N/A'))}"
        )
        return {
            "title": title,
            "description": desc,
            "tags": meta.get("tags", [])[:8],
        }
