from __future__ import annotations

import app._ssl_patch  # noqa: F401 — must be first: replaces system CA with certifi

import argparse
import logging
import threading
import time

from app.api import run_api_server
from app.download_service import run_discovery_and_download
from app.process_service import run_process_pipeline, run_process_poller
from app.logging_utils import setup_logging
from app.settings import settings


def run_scheduler() -> None:
    """Run a single discovery + download + cleanup + process cycle, then exit.
    Entry point: yp-scheduler
    """
    setup_logging(settings.log_level, settings.log_file)
    logger = logging.getLogger(__name__)
    logger.info('Scheduler: starting single cycle')

    summary = run_discovery_and_download()
    print(f'discovered={summary["discovered"]} persisted={summary["persisted"]} '
          f'downloaded={summary["downloaded"]} failed={summary["failed"]} '
          f'cleaned={summary["cleaned"]}')

    if summary.get("downloaded", 0) > 0 and settings.process_enabled:
        logger.info('Scheduler: triggering process pipeline for newly downloaded videos')
        proc = run_process_pipeline()
        print(f'processed={proc.get("processed", 0)} failed={proc.get("failed", 0)} '
              f'skipped={proc.get("skipped", 0)}')

    logger.info('Scheduler: cycle complete')


def run_server() -> None:
    """Start HTTP API + background discovery timer + process poller (blocking).
    Entry point: yp-server
    """
    setup_logging(settings.log_level, settings.log_file)
    logger = logging.getLogger(__name__)

    server = run_api_server()
    print(f'API server listening on http://{settings.api_host}:{settings.api_port}')

    # Discovery poller
    disc_interval_sec = max(60, int(settings.discovery_interval_minutes) * 60)

    def _discovery_loop() -> None:
        time.sleep(10)
        while True:
            logger.info('Timer: triggering scheduled discovery cycle')
            try:
                summary = run_discovery_and_download()
                logger.info('Timer: cycle complete — %s', summary)
            except Exception as exc:
                logger.error('Timer: cycle failed — %s', exc, exc_info=True)
            time.sleep(disc_interval_sec)

    disc_thread = threading.Thread(target=_discovery_loop, daemon=True, name='discovery-timer')
    disc_thread.start()
    print(f'Discovery timer started (interval={settings.discovery_interval_minutes} min)')

    # Process poller (runs independently, handles both new and retried videos)
    if settings.process_enabled:
        proc_thread = run_process_poller()
        print(f'Process poller started (interval={settings.process_poll_interval_sec}s)')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('Server shutting down')
        server.shutdown()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='YouTube搬运系统 - 香港服务器端')
    p.add_argument('mode', nargs='?', default='server',
                   choices=['scheduler', 'server'],
                   help='Run mode (default: server)')
    args = p.parse_args()
    {'scheduler': run_scheduler, 'server': run_server}[args.mode]()
