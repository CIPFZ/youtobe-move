from __future__ import annotations

import app._ssl_patch  # noqa: F401 — must be first: replaces system CA with certifi

import argparse
import logging
import threading
import time

from app.api import run_api_server
from app.download_service import run_discovery_and_download
from app.logging_utils import setup_logging
from app.settings import settings


def run_scheduler() -> None:
    """Run a single discovery + download + cleanup cycle, then exit.
    Entry point: hk-scheduler
    """
    setup_logging(settings.log_level, settings.log_file)
    logger = logging.getLogger(__name__)
    logger.info('Scheduler: starting single cycle')

    summary = run_discovery_and_download()
    if summary.get("skipped"):
        print(f'skipped=True reason={summary.get("reason", "")}')
        logger.info('Scheduler: cycle skipped — %s', summary)
        return
    print(
        f'discovered={summary["discovered"]} persisted={summary["persisted"]} '
        f'downloaded={summary["downloaded"]} failed={summary["failed"]} '
        f'expired={summary["expired"]}'
    )
    logger.info('Scheduler: cycle complete')


def run_server() -> None:
    """Start HTTP API + background discovery timer (blocking).
    Entry point: hk-server
    """
    setup_logging(settings.log_level, settings.log_file)
    logger = logging.getLogger(__name__)

    server = run_api_server()
    print(f'API server listening on http://{settings.api_host}:{settings.api_port}')

    # Discovery poller. 0 disables scheduled discovery so deployments can run
    # manual smoke tests without immediately starting a long yt-dlp search.
    if int(settings.discovery_interval_minutes) > 0:
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
    else:
        logger.info('Discovery timer disabled (DISCOVERY_INTERVAL_MINUTES=%s)', settings.discovery_interval_minutes)
        print('Discovery timer disabled')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('Server shutting down')
        server.shutdown()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='HK YouTube搬运服务')
    p.add_argument('mode', nargs='?', default='server',
                   choices=['scheduler', 'server'],
                   help='Run mode (default: server)')
    args = p.parse_args()
    {'scheduler': run_scheduler, 'server': run_server}[args.mode]()
