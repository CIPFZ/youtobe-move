#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from app.ffmpeg_tools import run_ffmpeg
from app.settings import settings
from app.transcriber import FastWhisperTranscriber


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Real transcriber functional test (no mock).')
    p.add_argument('--audio', type=Path, help='Input audio file path. If omitted, synthetic audio is generated.')
    p.add_argument('--seconds', type=int, default=2, help='Synthetic audio duration.')
    p.add_argument('--model', type=str, default='tiny', help='Whisper model name/path for this test run.')
    p.add_argument('--source', type=str, default='huggingface', choices=['huggingface', 'modelscope'], help='Whisper model source.')
    p.add_argument('--language', type=str, default='en', help='Transcription language.')
    p.add_argument('--run-real', action='store_true', help='Actually run transcription; otherwise skip.')
    return p.parse_args()


def _run_transcribe(audio_path: Path, model: str, source: str, language: str) -> int:
    old_model = settings.whisper_model
    old_source = settings.whisper_model_source
    old_local = settings.whisper_download_to_local
    old_lang = settings.whisper_language
    try:
        settings.whisper_model = model
        settings.whisper_model_source = source
        settings.whisper_download_to_local = False
        settings.whisper_language = language

        worker = FastWhisperTranscriber()
        items = worker.transcribe(str(audio_path))
        if len(items) < 1:
            raise RuntimeError('transcriber returned empty result')
        return len(items)
    finally:
        settings.whisper_model = old_model
        settings.whisper_model_source = old_source
        settings.whisper_download_to_local = old_local
        settings.whisper_language = old_lang


def main() -> int:
    args = parse_args()
    if not args.run_real:
        print('[SKIP] transcriber stage skipped: add --run-real to execute real transcription')
        return 0
    if args.audio:
        count = _run_transcribe(args.audio.resolve(), args.model, args.source, args.language)
        print(f'[OK] transcriber stage completed: segments={count}')
        return 0

    with tempfile.TemporaryDirectory(prefix='transcriber-stage-') as td:
        audio = Path(td) / 'speech.wav'
        run_ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=16000', '-t', str(args.seconds), '-ac', '1', str(audio)])
        count = _run_transcribe(audio, args.model, args.source, args.language)
        print(f'[OK] transcriber stage completed: segments={count}')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
