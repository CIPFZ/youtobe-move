#!/usr/bin/env python3
from __future__ import annotations

import argparse
import http.server
import socketserver
import tempfile
import threading
from pathlib import Path

from app.downloader import download_media
from app.ffmpeg_tools import run_ffmpeg
from app.settings import settings


class _ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def _generate_source_video(path: Path, seconds: int) -> None:
    run_ffmpeg([
        '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=24',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100',
        '-t', str(seconds),
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
        str(path),
    ])


def run_test(url: str | None, out_dir: Path, seconds: int) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    old_vfmt = settings.ytdlp_video_format
    old_afmt = settings.ytdlp_audio_format
    settings.ytdlp_video_format = 'best'
    settings.ytdlp_audio_format = 'bestaudio/best'
    try:
        result = download_media(url=url, out_dir=out_dir)
    finally:
        settings.ytdlp_video_format = old_vfmt
        settings.ytdlp_audio_format = old_afmt

    video_path = Path(result['video_path'])
    audio_path = Path(result['audio_path'])
    if not video_path.exists() or not audio_path.exists():
        raise RuntimeError('download_media did not produce valid video/audio files')
    if not result.get('metadata', {}).get('id'):
        raise RuntimeError('download_media metadata missing id')
    return video_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Real downloader functional test (no mock).')
    parser.add_argument('--url', type=str, default='', help='Media URL to download. If empty, synthetic local HTTP source is used.')
    parser.add_argument('--out-dir', type=Path, default=Path('runtime/test_downloader_stage'), help='Output directory for downloaded files.')
    parser.add_argument('--seconds', type=int, default=2, help='Duration for synthetic source media.')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.url.strip():
        out_video = run_test(url=args.url.strip(), out_dir=args.out_dir.resolve(), seconds=args.seconds)
        print(f'[OK] downloader stage completed: {out_video}')
        return 0

    with tempfile.TemporaryDirectory(prefix='downloader-stage-') as td:
        root = Path(td)
        source = root / 'source.mp4'
        _generate_source_video(source, args.seconds)

        handler = lambda *a, **kw: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **kw)
        with _ReusableTCPServer(('127.0.0.1', 0), handler) as httpd:
            port = httpd.server_address[1]
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                url = f'http://127.0.0.1:{port}/source.mp4'
                out_video = run_test(url=url, out_dir=args.out_dir.resolve(), seconds=args.seconds)
                print(f'[OK] downloader stage completed: {out_video}')
            finally:
                httpd.shutdown()
                thread.join(timeout=3)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
