#!/usr/bin/env python3
from __future__ import annotations

"""Download and prepare fast-whisper model to local directory.

Usage:
  python tests/download_fast_whisper_model.py
"""

from pathlib import Path

from app.logging_utils import setup_logging
from app.settings import settings
from app.transcriber import (
    _apply_download_proxy_env,
    _download_huggingface_model_to_local,
    _resolve_whisper_model_ref,
)


def main() -> int:
    setup_logging(settings.log_level, settings.log_file)
    try:
        _apply_download_proxy_env(settings.whisper_download_proxy.strip())

        source = settings.whisper_model_source.strip().lower()
        model_ref = settings.whisper_model.strip()

        if source == 'huggingface' and not Path(model_ref).expanduser().exists():
            local_path = _download_huggingface_model_to_local(
                model_ref=model_ref,
                cache_dir=settings.whisper_model_cache_dir.expanduser().resolve(),
            )
        else:
            local_path = _resolve_whisper_model_ref(source=source)

        print(f'Model prepared locally: {local_path}')
        return 0
    except Exception as exc:
        print(f'[ERROR] model prepare failed: {exc}')
        print('Tips:')
        print('  1) If using socks proxy, install dependency: pip install socksio')
        print('  2) Or switch to ModelScope in .env:')
        print('     WHISPER_MODEL_SOURCE=modelscope')
        print('     WHISPER_MODELSCOPE_REPO=<your_repo_id>')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
