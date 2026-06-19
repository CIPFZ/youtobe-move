from __future__ import annotations

import logging
import socket
import time
from typing import Any, Callable

from app.config import Config
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.discovery import discover_videos
from app.download_service import download_next
from app.publish_service import describe_next, publish_next


logger = logging.getLogger("youtube-pipeline")

WorkerStep = Callable[[], dict[str, Any]]


def _create_worker_event(config: Config, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        repo.create_event(None, None, "worker", event_type, message, payload)
        conn.commit()


def _run_step(name: str, step: WorkerStep) -> dict[str, Any]:
    try:
        result = step()
        return {"step": name, "ok": True, "result": result}
    except Exception as exc:
        logger.exception("Worker step failed: %s", name)
        return {"step": name, "ok": False, "error": str(exc)}


def _count_active_queue(config: Config) -> int:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        return repo.count_active_queue()


def _maybe_discover(config: Config) -> dict[str, Any]:
    queue_size = _count_active_queue(config)
    min_queue_size = config.worker_discovery_min_queue_size
    if queue_size >= min_queue_size:
        return {
            "status": "skipped",
            "reason": "queue_above_threshold",
            "queue_size": queue_size,
            "min_queue_size": min_queue_size,
        }

    result = discover_videos(config, source_type=config.worker_discovery_source, dry_run=False)
    result["queue_size_before"] = queue_size
    result["min_queue_size"] = min_queue_size
    return result


def run_worker_once(config: Config, enable_publish: bool | None = None, publish_dry_run: bool | None = None) -> dict[str, Any]:
    publish_enabled = config.worker_enable_publish if enable_publish is None else enable_publish
    dry_run_publish = config.worker_publish_dry_run if publish_dry_run is None else publish_dry_run
    worker_id = socket.gethostname()

    _create_worker_event(
        config,
        "worker_run_started",
        "Worker run started",
        {
            "worker_id": worker_id,
            "discovery_enabled": config.worker_enable_discovery,
            "publish_enabled": publish_enabled,
            "publish_dry_run": dry_run_publish,
        },
    )
    steps: list[dict[str, Any]] = []
    if config.worker_enable_discovery:
        steps.append(_run_step("discovery", lambda: _maybe_discover(config)))
    else:
        steps.append(
            {
                "step": "discovery",
                "ok": True,
                "result": {"status": "skipped", "reason": "worker_discovery_disabled"},
            }
        )
    steps.append(_run_step("download", lambda: download_next(config)))
    steps.append(_run_step("describe", lambda: describe_next(config)))
    if publish_enabled:
        steps.append(_run_step("publish", lambda: publish_next(config, dry_run=dry_run_publish)))
    else:
        steps.append(
            {
                "step": "publish",
                "ok": True,
                "result": {"status": "skipped", "reason": "worker_publish_disabled"},
            }
        )

    ok = all(step["ok"] for step in steps)
    result = {"status": "ok" if ok else "failed", "worker_id": worker_id, "steps": steps}
    _create_worker_event(config, "worker_run_finished", "Worker run finished", result)
    return result


def run_worker_loop(
    config: Config,
    interval_seconds: int | None = None,
    enable_publish: bool | None = None,
    publish_dry_run: bool | None = None,
    max_runs: int | None = None,
) -> dict[str, Any]:
    interval = config.worker_interval_seconds if interval_seconds is None else interval_seconds
    runs: list[dict[str, Any]] = []
    run_count = 0
    while max_runs is None or run_count < max_runs:
        runs.append(
            run_worker_once(
                config,
                enable_publish=enable_publish,
                publish_dry_run=publish_dry_run,
            )
        )
        run_count += 1
        if max_runs is not None and run_count >= max_runs:
            break
        time.sleep(interval)
    return {"status": "stopped", "runs": runs}
