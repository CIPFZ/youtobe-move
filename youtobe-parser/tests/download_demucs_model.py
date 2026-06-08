#!/usr/bin/env python3
from __future__ import annotations

"""Pre-download demucs model and auto-detect CPU/GPU device.

Usage:
  python tests/download_demucs_model.py
"""

from app.audio_separation import _resolve_demucs_device, predownload_demucs_model
from app.logging_utils import setup_logging
from app.settings import settings


def main() -> int:
    setup_logging(settings.log_level, settings.log_file)
    try:
        device = _resolve_demucs_device()
        marker = predownload_demucs_model(cache_out_dir=settings.demucs_cache_dir)
        print(f'Demucs model prepared. model={settings.demucs_model} device={device}')
        print(f'Marker: {marker.resolve()}')
        return 0
    except Exception as exc:
        print(f'[ERROR] demucs model prepare failed: {exc}')
        print('Tips:')
        print('  1) install demucs: pip install demucs')
        print('  2) ensure ffmpeg is available or set FFMPEG_PATH')
        print('  3) set DEMUCS_DEVICE=cpu to force CPU if GPU env is unstable')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
