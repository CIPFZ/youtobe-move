from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, set_key

from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema


MASKED_VALUE = "********"


@dataclass(frozen=True)
class ConfigField:
    key: str
    group: str
    value_type: str
    editable: bool = True
    sensitive: bool = False
    choices: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None


CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField("PIPELINE_ENABLED", "pipeline", "bool"),
    ConfigField("WORKER_INTERVAL_SECONDS", "pipeline", "int", minimum=1, maximum=86400),
    ConfigField("WORKER_CRON", "pipeline", "string"),
    ConfigField("WORKER_ENABLE_DISCOVERY", "pipeline", "bool"),
    ConfigField("WORKER_ENABLE_DOWNLOAD", "pipeline", "bool"),
    ConfigField("WORKER_ENABLE_DESCRIBE", "pipeline", "bool"),
    ConfigField("WORKER_ENABLE_PUBLISH", "pipeline", "bool"),
    ConfigField("WORKER_PUBLISH_DRY_RUN", "pipeline", "bool"),
    ConfigField("WORKER_DISCOVERY_MIN_QUEUE_SIZE", "pipeline", "int", minimum=0, maximum=10000),
    ConfigField("WORKER_DISCOVERY_SOURCE", "pipeline", "string", choices=("", "search", "trending", "channel_uploads")),
    ConfigField("PUBLISH_MODE", "publish", "string", choices=("manual", "approved_auto", "full_auto")),
    ConfigField("PUBLISH_MIN_INTERVAL_SECONDS", "publish", "int", minimum=0, maximum=604800),
    ConfigField("PUBLISH_DAILY_LIMIT", "publish", "int", minimum=0, maximum=1000),
    ConfigField("PUBLISH_WINDOW_START", "publish", "time"),
    ConfigField("PUBLISH_WINDOW_END", "publish", "time"),
    ConfigField("BILIBILI_ACCOUNT", "publish", "string"),
    ConfigField("BILIBILI_TID_OPTIONS", "publish", "string"),
    ConfigField("STORAGE_MAX_GB", "storage", "float", minimum=0),
    ConfigField("STORAGE_WARN_GB", "storage", "float", minimum=0),
    ConfigField("STORAGE_MIN_FREE_GB", "storage", "float", minimum=0),
    ConfigField("STORAGE_RETENTION_DAYS", "storage", "int", minimum=0, maximum=3650),
    ConfigField("STORAGE_PUBLISHED_RETENTION_DAYS", "storage", "int", minimum=0, maximum=3650),
    ConfigField("STORAGE_CLEANUP_ENABLED", "storage", "bool"),
    ConfigField("STORAGE_CLEANUP_STATUSES", "storage", "string"),
    ConfigField("PROXY", "download", "string"),
    ConfigField("COOKIE_FILE", "download", "string"),
    ConfigField("VIDEO_FORMAT", "download", "string"),
    ConfigField("AUDIO_FORMAT", "download", "string"),
    ConfigField("SOCKET_TIMEOUT", "download", "float", minimum=1, maximum=300),
    ConfigField("RETRIES", "download", "int", minimum=0, maximum=100),
    ConfigField("FRAGMENT_RETRIES", "download", "int", minimum=0, maximum=100),
    ConfigField("RETRY_BACKOFF_FACTOR", "download", "float", minimum=0, maximum=60),
    ConfigField("YOUTUBE_API_KEY", "youtube", "string", sensitive=True),
    ConfigField("YOUTUBE_API_BASE", "youtube", "string"),
    ConfigField("YOUTUBE_VIDEO_PARTS", "youtube", "string"),
    ConfigField("YOUTUBE_SEARCH_PART", "youtube", "string"),
    ConfigField("YOUTUBE_SEARCH_TYPE", "youtube", "string"),
    ConfigField("YOUTUBE_SEARCH_ORDER", "youtube", "string"),
    ConfigField("DISCOVERY_SOURCES_JSON", "discovery", "json"),
    ConfigField("DISCOVERY_MAX_RESULTS_PER_SOURCE", "discovery", "int", minimum=1, maximum=50),
    ConfigField("DISCOVERY_MIN_DURATION_SECONDS", "discovery", "int", minimum=0, maximum=86400),
    ConfigField("DISCOVERY_MAX_DURATION_SECONDS", "discovery", "int", minimum=0, maximum=86400),
    ConfigField("DISCOVERY_MIN_VIEW_COUNT", "discovery", "int", minimum=0),
    ConfigField("DISCOVERY_TITLE_BLOCKLIST", "discovery", "string"),
    ConfigField("DISCOVERY_CHANNEL_ALLOWLIST", "discovery", "string"),
    ConfigField("DISCOVERY_CHANNEL_BLOCKLIST", "discovery", "string"),
    ConfigField("DISCOVERY_CATEGORY_ALLOWLIST", "discovery", "string"),
    ConfigField("DISCOVERY_CATEGORY_BLOCKLIST", "discovery", "string"),
    ConfigField("MINIMAX_ANTHROPIC_BASE_URL", "llm", "string"),
    ConfigField("MINIMAX_ANTHROPIC_API_KEY", "llm", "string", sensitive=True),
    ConfigField("MINIMAX_ANTHROPIC_MODEL", "llm", "string"),
    ConfigField("MINIMAX_ANTHROPIC_VERSION", "llm", "string"),
    ConfigField("MINIMAX_REQUEST_TIMEOUT", "llm", "int", minimum=1, maximum=600),
    ConfigField("MINIMAX_MAX_TOKENS", "llm", "int", minimum=1, maximum=8192),
    ConfigField("JOB_LEASE_SECONDS", "jobs", "int", minimum=1, maximum=86400),
    ConfigField("JOB_RETRY_BASE_SECONDS", "jobs", "int", minimum=1, maximum=86400),
    ConfigField("JOB_RETRY_MAX_SECONDS", "jobs", "int", minimum=1, maximum=604800),
    ConfigField("OUTPUT_DIR", "paths", "string"),
    ConfigField("DB_PATH", "paths", "string"),
    ConfigField("TMP_DIR", "paths", "string"),
    ConfigField("SOCIAL_AUTO_UPLOAD_DIR", "paths", "string"),
    ConfigField("FFMPEG_BIN", "paths", "string"),
    ConfigField("LOG_LEVEL", "logging", "string", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
    ConfigField("LOG_FILE", "logging", "string"),
    ConfigField("WEB_HOST", "web", "string"),
    ConfigField("WEB_PORT", "web", "int", minimum=1, maximum=65535),
)

CONFIG_FIELD_BY_KEY = {field.key: field for field in CONFIG_FIELDS}


def _env_path(base_dir: Path | None = None) -> Path:
    return (base_dir or Path.cwd()) / ".env"


def _read_env(env_path: Path) -> dict[str, str]:
    values = {key: value or "" for key, value in dotenv_values(env_path).items()}
    for key in CONFIG_FIELD_BY_KEY:
        if key not in values and key in os.environ:
            values[key] = os.environ[key]
    return values


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Invalid bool value: {value}")


def _validate_time(value: str) -> str:
    value = value.strip()
    if value == "":
        return value
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time value: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time value: {value}")
    return f"{hour:02d}:{minute:02d}"


def _validate_string(value: Any) -> str:
    text = str(value)
    if "\n" in text or "\r" in text:
        raise ValueError("Config values cannot contain newlines")
    return text


def _coerce_value(field: ConfigField, value: Any) -> str:
    if field.sensitive and value == MASKED_VALUE:
        raise ValueError(f"Sensitive config cannot be saved with masked value: {field.key}")

    if field.value_type == "bool":
        coerced = "true" if _parse_bool(value) else "false"
    elif field.value_type == "int":
        number = int(value)
        if field.minimum is not None and number < field.minimum:
            raise ValueError(f"{field.key} must be >= {field.minimum}")
        if field.maximum is not None and number > field.maximum:
            raise ValueError(f"{field.key} must be <= {field.maximum}")
        coerced = str(number)
    elif field.value_type == "float":
        number = float(value)
        if field.minimum is not None and number < field.minimum:
            raise ValueError(f"{field.key} must be >= {field.minimum}")
        if field.maximum is not None and number > field.maximum:
            raise ValueError(f"{field.key} must be <= {field.maximum}")
        coerced = str(number)
    elif field.value_type == "time":
        coerced = _validate_time(str(value))
    elif field.value_type == "json":
        if isinstance(value, str):
            parsed = json.loads(value)
        else:
            parsed = value
        coerced = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    else:
        coerced = _validate_string(value)

    if field.choices and coerced not in field.choices:
        raise ValueError(f"{field.key} must be one of: {', '.join(field.choices)}")
    return coerced


def _display_value(field: ConfigField, raw_value: str) -> Any:
    if field.sensitive:
        return MASKED_VALUE if raw_value else ""
    if field.value_type == "bool":
        try:
            return _parse_bool(raw_value)
        except ValueError:
            return raw_value
    if field.value_type == "int":
        try:
            return int(raw_value)
        except ValueError:
            return raw_value
    if field.value_type == "float":
        try:
            return float(raw_value)
        except ValueError:
            return raw_value
    if field.value_type == "json":
        try:
            return json.loads(raw_value)
        except json.JSONDecodeError:
            return raw_value
    return raw_value


def list_config(base_dir: Path | None = None) -> dict[str, Any]:
    env_path = _env_path(base_dir)
    raw_values = _read_env(env_path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for field in CONFIG_FIELDS:
        raw_value = raw_values.get(field.key, "")
        groups.setdefault(field.group, []).append(
            {
                "key": field.key,
                "value": _display_value(field, raw_value),
                "type": field.value_type,
                "editable": field.editable,
                "sensitive": field.sensitive,
                "choices": list(field.choices),
            }
        )
    return {"env_path": str(env_path), "groups": groups}


def _write_audit_event(base_dir: Path, db_path_value: str, updated_keys: list[str], actor: str) -> None:
    db_path = Path(db_path_value)
    if not db_path.is_absolute():
        db_path = base_dir / db_path
    with connect(db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        repo.create_event(
            None,
            None,
            "config",
            "config_updated",
            "Configuration updated",
            {"actor": actor, "keys": updated_keys},
        )
        conn.commit()


def update_config(
    updates: dict[str, Any],
    base_dir: Path | None = None,
    actor: str = "web",
) -> dict[str, Any]:
    if not updates:
        return {"updated": [], "config": list_config(base_dir)}

    env_path = _env_path(base_dir)
    base = env_path.parent
    raw_values = _read_env(env_path)
    coerced_updates: dict[str, str] = {}
    for key, value in updates.items():
        field = CONFIG_FIELD_BY_KEY.get(key)
        if field is None:
            raise ValueError(f"Unsupported config key: {key}")
        if not field.editable:
            raise ValueError(f"Config key is not editable: {key}")
        coerced_updates[key] = _coerce_value(field, value)

    for key, value in coerced_updates.items():
        set_key(str(env_path), key, value, quote_mode="never")
        os.environ[key] = value

    updated_keys = sorted(coerced_updates)
    db_path_value = coerced_updates.get("DB_PATH") or raw_values.get("DB_PATH", "runtime/data/pipeline.db")
    _write_audit_event(base, db_path_value, updated_keys, actor)
    return {"updated": updated_keys, "config": list_config(base)}
