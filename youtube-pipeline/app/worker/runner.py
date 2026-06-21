from __future__ import annotations

import logging
import socket
import threading
import time
from datetime import datetime
from typing import Any, Callable

from app.config import Config, load_config
from app.cron_schedule import seconds_until_next_cron
from app.core.db import connect
from app.core.repository import Repository
from app.core.schema import init_schema
from app.discovery import discover_videos
from app.download_service import download_next
from app.publish_service import describe_next, publish_next
from app.storage import cleanup_media


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


def _recover_stale_jobs(config: Config, worker_id: str) -> dict[str, Any]:
    with connect(config.db_path) as conn:
        init_schema(conn)
        repo = Repository(conn)
        return repo.recover_stale_jobs(worker_id, getattr(config, "job_lease_seconds", 1800))


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
            "pipeline_enabled": getattr(config, "pipeline_enabled", True),
            "job_lease_seconds": getattr(config, "job_lease_seconds", 1800),
            "discovery_enabled": config.worker_enable_discovery,
            "download_enabled": getattr(config, "worker_enable_download", True),
            "describe_enabled": getattr(config, "worker_enable_describe", True),
            "publish_enabled": publish_enabled,
            "publish_dry_run": dry_run_publish,
            "storage_cleanup_enabled": getattr(config, "storage_cleanup_enabled", False),
        },
    )
    steps: list[dict[str, Any]] = []
    steps.append(_run_step("recover", lambda: _recover_stale_jobs(config, worker_id)))
    if not getattr(config, "pipeline_enabled", True):
        steps.extend(
            [
                {"step": "discovery", "ok": True, "result": {"status": "skipped", "reason": "pipeline_disabled"}},
                {"step": "download", "ok": True, "result": {"status": "skipped", "reason": "pipeline_disabled"}},
                {"step": "describe", "ok": True, "result": {"status": "skipped", "reason": "pipeline_disabled"}},
                {"step": "publish", "ok": True, "result": {"status": "skipped", "reason": "pipeline_disabled"}},
                {"step": "storage_cleanup", "ok": True, "result": {"status": "skipped", "reason": "pipeline_disabled"}},
            ]
        )
        ok = all(step["ok"] for step in steps)
        result = {"status": "ok" if ok else "failed", "worker_id": worker_id, "steps": steps}
        _create_worker_event(config, "worker_run_finished", "Worker run finished", result)
        return result

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
    if getattr(config, "worker_enable_download", True):
        steps.append(_run_step("download", lambda: download_next(config, worker_id=worker_id)))
    else:
        steps.append(
            {
                "step": "download",
                "ok": True,
                "result": {"status": "skipped", "reason": "worker_download_disabled"},
            }
        )
    if getattr(config, "worker_enable_describe", True):
        steps.append(_run_step("describe", lambda: describe_next(config, worker_id=worker_id)))
    else:
        steps.append(
            {
                "step": "describe",
                "ok": True,
                "result": {"status": "skipped", "reason": "worker_describe_disabled"},
            }
        )
    if publish_enabled:
        steps.append(_run_step("publish", lambda: publish_next(config, dry_run=dry_run_publish, worker_id=worker_id)))
    else:
        steps.append(
            {
                "step": "publish",
                "ok": True,
                "result": {"status": "skipped", "reason": "worker_publish_disabled"},
            }
        )
    if getattr(config, "storage_cleanup_enabled", False):
        steps.append(_run_step("storage_cleanup", lambda: cleanup_media(config, dry_run=False)))
    else:
        steps.append(
            {
                "step": "storage_cleanup",
                "ok": True,
                "result": {"status": "skipped", "reason": "storage_cleanup_disabled"},
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
    config_loader: Callable[[], Config] | None = load_config,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    run_count = 0
    current_config = config
    schedule_mode = "interval"
    while max_runs is None or run_count < max_runs:
        if config_loader is not None:
            try:
                current_config = config_loader()
            except Exception:
                logger.exception("Worker config reload failed; using previous config")
        runs.append(
            run_worker_once(
                current_config,
                enable_publish=enable_publish,
                publish_dry_run=publish_dry_run,
            )
        )
        run_count += 1
        if max_runs is not None and run_count >= max_runs:
            break
        if config_loader is not None:
            try:
                current_config = config_loader()
            except Exception:
                logger.exception("Worker config reload before sleep failed; using previous config")
        interval = current_config.worker_interval_seconds if interval_seconds is None else interval_seconds
        cron_expression = str(getattr(current_config, "worker_cron", "") or "").strip() if interval_seconds is None else ""
        schedule_mode = "cron" if cron_expression else "interval"
        sleep_seconds = seconds_until_next_cron(cron_expression, datetime.now()) if cron_expression else interval
        logger.info(
            "Worker loop sleeping: mode=%s seconds=%.1f",
            schedule_mode,
            sleep_seconds,
        )
        if stop_event is not None:
            if stop_event.wait(sleep_seconds):
                break
        else:
            time.sleep(sleep_seconds)
    return {"status": "stopped", "runs": runs, "schedule_mode": schedule_mode}


def _run_scheduled_step(
    config: Config,
    worker_id: str,
    step_name: str,
    step: WorkerStep,
    enabled: bool = True,
    disabled_reason: str = "disabled",
) -> dict[str, Any]:
    if not getattr(config, "pipeline_enabled", True):
        result = {"status": "skipped", "reason": "pipeline_disabled"}
    elif not enabled:
        result = {"status": "skipped", "reason": disabled_reason}
    else:
        result = _run_step(step_name, step)
    _create_worker_event(
        config,
        "worker_step_finished",
        f"Worker scheduled step finished: {step_name}",
        {"worker_id": worker_id, "step": step_name, "result": result},
    )
    return result


def run_embedded_scheduler_loop(
    config: Config,
    stop_event: threading.Event | None = None,
    config_loader: Callable[[], Config] | None = load_config,
    max_ticks: int | None = None,
) -> dict[str, Any]:
    worker_id = socket.gethostname()
    tick = 0
    last_discovery_at = 0.0
    last_queue_at = 0.0
    last_publish_at = 0.0
    current_config = config
    _create_worker_event(config, "worker_scheduler_started", "Embedded worker scheduler started", {"worker_id": worker_id})

    while max_ticks is None or tick < max_ticks:
        now = time.monotonic()
        if config_loader is not None:
            try:
                current_config = config_loader()
            except Exception:
                logger.exception("Worker scheduler config reload failed; using previous config")

        discovery_interval = max(1, int(getattr(current_config, "worker_interval_seconds", 21600)))
        queue_interval = max(1, int(getattr(current_config, "worker_queue_interval_seconds", 60)))
        publish_interval = max(1, int(getattr(current_config, "worker_publish_interval_seconds", 300)))
        ran_any = False

        steps: list[dict[str, Any]] = []
        if last_discovery_at == 0 or now - last_discovery_at >= discovery_interval:
            steps.append(_run_step("recover", lambda: _recover_stale_jobs(current_config, worker_id)))
            steps.append(
                _run_scheduled_step(
                    current_config,
                    worker_id,
                    "discovery",
                    lambda: _maybe_discover(current_config),
                    enabled=current_config.worker_enable_discovery,
                    disabled_reason="worker_discovery_disabled",
                )
            )
            last_discovery_at = time.monotonic()
            ran_any = True

        if last_queue_at == 0 or now - last_queue_at >= queue_interval:
            steps.append(_run_step("recover", lambda: _recover_stale_jobs(current_config, worker_id)))
            steps.append(
                _run_scheduled_step(
                    current_config,
                    worker_id,
                    "download",
                    lambda: download_next(current_config, worker_id=worker_id),
                    enabled=getattr(current_config, "worker_enable_download", True),
                    disabled_reason="worker_download_disabled",
                )
            )
            steps.append(
                _run_scheduled_step(
                    current_config,
                    worker_id,
                    "describe",
                    lambda: describe_next(current_config, worker_id=worker_id),
                    enabled=getattr(current_config, "worker_enable_describe", True),
                    disabled_reason="worker_describe_disabled",
                )
            )
            last_queue_at = time.monotonic()
            ran_any = True

        if last_publish_at == 0 or now - last_publish_at >= publish_interval:
            publish_enabled = current_config.worker_enable_publish
            dry_run_publish = current_config.worker_publish_dry_run
            steps.append(
                _run_scheduled_step(
                    current_config,
                    worker_id,
                    "publish",
                    lambda: publish_next(current_config, dry_run=dry_run_publish, worker_id=worker_id),
                    enabled=publish_enabled,
                    disabled_reason="worker_publish_disabled",
                )
            )
            last_publish_at = time.monotonic()
            ran_any = True

        if ran_any:
            _create_worker_event(
                current_config,
                "worker_scheduler_tick_finished",
                "Embedded worker scheduler tick finished",
                {"worker_id": worker_id, "steps": steps},
            )
            tick += 1

        next_due = min(
            max(1.0, discovery_interval - (time.monotonic() - last_discovery_at)),
            max(1.0, queue_interval - (time.monotonic() - last_queue_at)),
            max(1.0, publish_interval - (time.monotonic() - last_publish_at)),
        )
        logger.info("Embedded worker scheduler sleeping: seconds=%.1f", next_due)
        if stop_event is not None:
            if stop_event.wait(next_due):
                break
        else:
            time.sleep(next_due)

    return {"status": "stopped", "ticks": tick}
