from __future__ import annotations

import logging
from pathlib import Path


def setup_logging(log_level: str, log_file: Path) -> None:
    """Configure root logger for console + file output."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)

    # avoid duplicate handlers when called multiple times
    if root.handlers:
        root.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(file_handler)
