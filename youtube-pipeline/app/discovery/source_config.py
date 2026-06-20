from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Config
from app.config_service import update_config


SUPPORTED_SOURCE_TYPES = {"search", "trending", "channel_uploads"}
SOURCE_FILTER_INT_FIELDS = ("min_duration_seconds", "max_duration_seconds", "min_view_count")
SOURCE_FILTER_TEXT_FIELDS = (
    "title_blocklist",
    "channel_allowlist",
    "channel_blocklist",
    "category_allowlist",
    "category_blocklist",
)


def _clean_string(value: Any) -> str:
    return str(value or "").strip()


def _parse_bool(value: Any, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Invalid bool value: {value}")


def normalize_discovery_source(source: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise ValueError("Discovery source must be an object")
    source_type = _clean_string(source.get("type"))
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(f"Unsupported discovery source type: {source_type}")

    result: dict[str, Any] = {"type": source_type}
    name = _clean_string(source.get("name"))
    if name:
        result["name"] = name
    result["enabled"] = _parse_bool(source.get("enabled"), default=True)
    result["priority"] = int(source.get("priority") if source.get("priority") not in (None, "") else 100)
    result["score_weight"] = float(source.get("score_weight") if source.get("score_weight") not in (None, "") else 1.0)
    if result["score_weight"] < 0:
        raise ValueError("Discovery source score_weight must be >= 0")

    max_results = int(source.get("max_results") or 0)
    if not (1 <= max_results <= 50):
        raise ValueError("Discovery source max_results must be between 1 and 50")
    result["max_results"] = max_results
    for key in SOURCE_FILTER_INT_FIELDS:
        value = source.get(key)
        if value not in (None, ""):
            parsed = int(value)
            if parsed < 0:
                raise ValueError(f"Discovery source {key} must be >= 0")
            result[key] = parsed
    for key in SOURCE_FILTER_TEXT_FIELDS:
        value = _clean_string(source.get(key))
        if value:
            result[key] = value

    if source_type == "search":
        keyword = _clean_string(source.get("keyword") or source.get("q"))
        if not keyword:
            raise ValueError("Search source requires keyword")
        result["keyword"] = keyword
        for key in ("order", "channel_id", "published_after", "region_code", "relevance_language", "video_category_id"):
            value = _clean_string(source.get(key))
            if value:
                result[key] = value
    elif source_type == "trending":
        result["region_code"] = _clean_string(source.get("region_code")) or "US"
        video_category_id = _clean_string(source.get("video_category_id"))
        if video_category_id:
            result["video_category_id"] = video_category_id
    elif source_type == "channel_uploads":
        channel_id = _clean_string(source.get("channel_id"))
        handle = _clean_string(source.get("handle"))
        if not channel_id and not handle:
            raise ValueError("channel_uploads source requires channel_id or handle")
        if channel_id:
            result["channel_id"] = channel_id
        if handle:
            result["handle"] = handle if handle.startswith("@") else f"@{handle}"

    return result


def parse_discovery_sources(raw: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"DISCOVERY_SOURCES_JSON is invalid JSON: {exc}") from exc
    if not isinstance(parsed, list):
        raise ValueError("DISCOVERY_SOURCES_JSON must be a JSON array")
    return [normalize_discovery_source(item) for item in parsed]


def list_discovery_source_configs(config: Config) -> dict[str, Any]:
    sources = parse_discovery_sources(config.discovery_sources_json)
    return {"sources": [{"index": index, **source} for index, source in enumerate(sources)]}


def _write_sources(config: Config, sources: list[dict[str, Any]]) -> dict[str, Any]:
    normalized = [normalize_discovery_source(source) for source in sources]
    update_config(
        {"DISCOVERY_SOURCES_JSON": normalized},
        Path(config.base_dir),
        actor="web",
    )
    return {"status": "ok", "sources": [{"index": index, **source} for index, source in enumerate(normalized)]}


def replace_discovery_sources(config: Config, sources: list[dict[str, Any]]) -> dict[str, Any]:
    return _write_sources(config, sources)


def add_discovery_source(config: Config, source: dict[str, Any]) -> dict[str, Any]:
    sources = parse_discovery_sources(config.discovery_sources_json)
    sources.append(normalize_discovery_source(source))
    return _write_sources(config, sources)


def update_discovery_source(config: Config, index: int, source: dict[str, Any]) -> dict[str, Any]:
    sources = parse_discovery_sources(config.discovery_sources_json)
    if not (0 <= index < len(sources)):
        raise IndexError(f"Discovery source index out of range: {index}")
    sources[index] = normalize_discovery_source(source)
    return _write_sources(config, sources)


def delete_discovery_source(config: Config, index: int) -> dict[str, Any]:
    sources = parse_discovery_sources(config.discovery_sources_json)
    if not (0 <= index < len(sources)):
        raise IndexError(f"Discovery source index out of range: {index}")
    deleted = sources.pop(index)
    result = _write_sources(config, sources)
    result["deleted"] = deleted
    return result
