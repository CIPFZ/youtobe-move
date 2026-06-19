from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from app.config import Config


logger = logging.getLogger("youtube-pipeline")


def _watch_paths(base_dir: Path) -> list[Path]:
    paths: list[Path] = [base_dir / "main.py", base_dir / ".env"]
    app_dir = base_dir / "app"
    if app_dir.exists():
        paths.extend(path for path in app_dir.rglob("*.py") if path.is_file())
    return paths


def _snapshot(paths: list[Path]) -> dict[str, int]:
    result: dict[str, int] = {}
    for path in paths:
        try:
            result[str(path)] = path.stat().st_mtime_ns
        except FileNotFoundError:
            result[str(path)] = -1
    return result


def _stop_process(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_web_dev_server(
    config: Config,
    host: str | None = None,
    port: int | None = None,
    poll_seconds: float = 1.0,
) -> None:
    bind_host = host or config.web_host
    bind_port = port or config.web_port
    vite_port = bind_port + 1
    base_dir = config.base_dir
    web_dir = base_dir / "web"
    backend_command = [
        sys.executable,
        str(base_dir / "main.py"),
        "web",
        "--host",
        bind_host,
        "--port",
        str(bind_port),
    ]
    vite_env = {
        **os.environ,
        "VITE_API_TARGET": f"http://{bind_host}:{bind_port}",
        "VITE_PORT": str(vite_port),
    }
    vite_command = ["npm", "run", "dev", "--", "--host", bind_host]

    logger.info("Web dev server watching Python files and .env")
    logger.info("React dev UI will run at: http://%s:%s", bind_host, vite_port)
    watched = _watch_paths(base_dir)
    last_snapshot = _snapshot(watched)
    backend_process: subprocess.Popen[object] | None = None
    vite_process: subprocess.Popen[object] | None = None
    try:
        while True:
            if backend_process is None or backend_process.poll() is not None:
                logger.info("Starting API child process: http://%s:%s", bind_host, bind_port)
                backend_process = subprocess.Popen(backend_command, cwd=str(base_dir))
            if vite_process is None or vite_process.poll() is not None:
                logger.info("Starting Vite child process")
                vite_process = subprocess.Popen(vite_command, cwd=str(web_dir), env=vite_env)

            time.sleep(max(0.2, poll_seconds))
            watched = _watch_paths(base_dir)
            current_snapshot = _snapshot(watched)
            if current_snapshot != last_snapshot:
                logger.info("Python source changed; restarting API child process")
                _stop_process(backend_process)
                backend_process = subprocess.Popen(backend_command, cwd=str(base_dir))
                last_snapshot = current_snapshot
    except KeyboardInterrupt:
        logger.info("Stopping Web dev server")
    finally:
        if vite_process is not None:
            _stop_process(vite_process)
        if backend_process is not None:
            _stop_process(backend_process)
