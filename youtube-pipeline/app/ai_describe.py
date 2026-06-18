from __future__ import annotations

import logging
import re
from typing import Any

import requests

from app.config import Config


logger = logging.getLogger("youtube-pipeline")


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

TID_PROMPT = """你是一个 Bilibili 分区选择助手。
你需要根据 YouTube 视频元数据，从给定的 Bilibili 分区白名单中选择最合适的 tid。

判断优先级：
1. YouTube categories / categoryId / topicCategories
2. tags
3. description
4. channel/uploader
5. title 只能作为兜底参考

只能输出下面两行，不要 Markdown，不要额外解释：
分区ID：数字
理由：一句中文理由"""


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
    description = re.sub(r"(?:YouTube)?原视频(?:链接)?[：:]\s*$", "", description).strip()
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    if description:
        return f"{description}\n\n原视频链接：{original_url}"
    return f"原视频链接：{original_url}"


def _call_ai(config: Config, messages: list[dict[str, str]]) -> str:
    if not config.minimax_anthropic_api_key:
        raise RuntimeError("MINIMAX_ANTHROPIC_API_KEY is not configured")

    response = requests.post(
        f"{config.minimax_anthropic_base_url}/v1/messages",
        headers={
            "Authorization": f"Bearer {config.minimax_anthropic_api_key}",
            "Content-Type": "application/json",
            "anthropic-version": config.minimax_anthropic_version,
        },
        json={
            "model": config.minimax_anthropic_model,
            "max_tokens": config.minimax_max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": messages,
        },
        timeout=config.minimax_request_timeout,
    )
    response.raise_for_status()
    payload = response.json()
    text_parts = []
    for block in payload.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    return "".join(text_parts)


def _call_ai_with_system(config: Config, system_prompt: str, messages: list[dict[str, str]]) -> str:
    if not config.minimax_anthropic_api_key:
        raise RuntimeError("MINIMAX_ANTHROPIC_API_KEY is not configured")

    response = requests.post(
        f"{config.minimax_anthropic_base_url}/v1/messages",
        headers={
            "Authorization": f"Bearer {config.minimax_anthropic_api_key}",
            "Content-Type": "application/json",
            "anthropic-version": config.minimax_anthropic_version,
        },
        json={
            "model": config.minimax_anthropic_model,
            "max_tokens": config.minimax_max_tokens,
            "system": system_prompt,
            "messages": messages,
        },
        timeout=config.minimax_request_timeout,
    )
    response.raise_for_status()
    payload = response.json()
    text_parts = []
    for block in payload.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
    return "".join(text_parts)


def _parse_metadata_text(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {"title": "", "description": "", "tags": []}
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if line.startswith("标题：") or line.startswith("标题:"):
            result["title"] = _strip_field_prefix(line, "标题")
        elif line.startswith("描述：") or line.startswith("描述:"):
            result["description"] = _strip_field_prefix(line, "描述")
        elif line.startswith("标签：") or line.startswith("标签:"):
            raw_tags = _strip_field_prefix(line, "标签")
            tags = raw_tags.replace(",", "，").split("，")
            result["tags"] = [tag.strip().lstrip("#") for tag in tags if tag.strip()]
    if not result["title"] or not result["description"]:
        raise ValueError(f"AI response does not match metadata format: {text[:200]}")
    return result


def _strip_field_prefix(line: str, field_name: str) -> str:
    for separator in ("：", ":"):
        prefix = f"{field_name}{separator}"
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return line.strip()


def parse_tid_options(raw: str) -> dict[int, str]:
    options: dict[int, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            continue
        tid_text, label = item.split(":", 1)
        try:
            tid = int(tid_text.strip())
        except ValueError:
            continue
        options[tid] = label.strip()
    return options


def _parse_tid_selection(text: str) -> tuple[int, str]:
    tid = 0
    reason = ""
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if line.startswith("分区ID：") or line.startswith("分区ID:"):
            tid_text = _strip_field_prefix(line, "分区ID")
            tid = int(re.search(r"\d+", tid_text).group(0)) if re.search(r"\d+", tid_text) else 0
        elif line.startswith("理由：") or line.startswith("理由:"):
            reason = _strip_field_prefix(line, "理由")
    if not tid:
        raise ValueError(f"AI response does not contain tid: {text[:200]}")
    return tid, reason


def select_bilibili_tid(meta: dict[str, Any], config: Config) -> dict[str, Any]:
    options = parse_tid_options(config.bilibili_tid_options)
    if not options:
        return {
            "tid": config.bilibili_tid,
            "label": "",
            "reason": "BILIBILI_TID_OPTIONS is empty, fallback to BILIBILI_TID",
            "source": "fallback",
        }

    video_info = {
        "title": meta.get("title", meta.get("fulltitle", "")),
        "channel": meta.get("channel", meta.get("uploader", "")),
        "categories": meta.get("categories", []),
        "tags": meta.get("tags", [])[:20],
        "description": str(meta.get("description", ""))[:800],
        "duration": meta.get("duration_string", meta.get("duration", "")),
        "language": meta.get("language", ""),
    }
    options_text = "\n".join(f"{tid}: {label}" for tid, label in sorted(options.items()))
    meta_text = "\n".join(f"{key}: {value}" for key, value in video_info.items())
    prompt = f"可选 Bilibili 分区：\n{options_text}\n\nYouTube 视频元数据：\n{meta_text}"

    try:
        raw = _call_ai_with_system(config, TID_PROMPT, [{"role": "user", "content": prompt}])
        tid, reason = _parse_tid_selection(raw)
        if tid not in options:
            raise ValueError(f"AI selected tid {tid}, not in allowed options")
        return {
            "tid": tid,
            "label": options[tid],
            "reason": reason,
            "source": "llm",
        }
    except Exception as exc:
        logger.warning("AI tid selection failed: %s, fallback to BILIBILI_TID", exc)
        return {
            "tid": config.bilibili_tid,
            "label": options.get(config.bilibili_tid, ""),
            "reason": f"LLM tid selection failed: {exc}",
            "source": "fallback",
        }


def generate_chinese_metadata(meta: dict[str, Any], config: Config) -> dict[str, Any]:
    video_id = str(meta.get("id", ""))
    original_url = str(meta.get("webpage_url") or meta.get("original_url") or f"https://www.youtube.com/watch?v={video_id}")
    video_info = {
        "标题": meta.get("title", meta.get("fulltitle", "")),
        "频道": meta.get("channel", meta.get("uploader", "")),
        "时长": meta.get("duration_string", f'{meta.get("duration", 0)}秒'),
        "播放量": f"{meta.get('view_count', 0):,}",
        "点赞数": f"{meta.get('like_count', 0):,}",
        "标签": meta.get("tags", [])[:10],
        "分类": meta.get("categories", []),
        "YouTube链接": original_url,
    }
    original_desc = meta.get("description", "")
    if original_desc:
        video_info["原始描述"] = original_desc[:500]

    user_msg = "\n".join(f"{key}: {value}" for key, value in video_info.items())
    prompt = f"请根据以下视频信息生成中文发布内容：\n\n{user_msg}"

    try:
        raw = _call_ai(config, [{"role": "user", "content": prompt}])
        result = _parse_metadata_text(raw)
        result["description"] = normalize_source_description(result.get("description", ""), original_url)
        logger.info("AI generated Chinese metadata for %s", video_id)
        return result
    except Exception as exc:
        logger.warning("AI metadata generation failed: %s, using fallback", exc)
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
