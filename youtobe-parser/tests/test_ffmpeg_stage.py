#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

from app.ffmpeg_tools import ffmpeg_bin, merge_av_with_ass, run_ffmpeg


def _write_ass(path: Path) -> None:
    path.write_text(
        '[Script Info]\nScriptType: v4.00+\nPlayResX: 640\nPlayResY: 360\n\n[V4+ Styles]\n'
        'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
        'Style: Default,Arial,36,&H00FFFFFF,&H0000FFFF,&H00000000,&H55000000,-1,0,0,0,100,100,0,0,1,2,0,2,20,20,20,1\n\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        'Dialogue: 0,0:00:00.00,0:00:01.50,Default,,0,0,0,,ffmpeg stage test\n',
        encoding='utf-8',
    )


def _assert_av_streams(path: Path) -> None:
    probe = subprocess.run([ffmpeg_bin(), '-i', str(path), '-f', 'null', '-'], text=True, capture_output=True, check=False)
    if 'Video:' not in probe.stderr or 'Audio:' not in probe.stderr:
        raise RuntimeError('merged output missing audio or video stream')


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Real ffmpeg stage functional test (no mock).')
    p.add_argument('--video', type=Path, help='Input video file. If omitted, synthetic video is generated.')
    p.add_argument('--audio', type=Path, help='Input audio file. If omitted, synthetic audio is generated.')
    p.add_argument('--ass', type=Path, help='Input ASS subtitle. If omitted, synthetic ASS is generated.')
    p.add_argument('--out', type=Path, help='Output merged mp4 path.')
    p.add_argument('--seconds', type=int, default=2, help='Synthetic media duration seconds.')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    ff = Path(ffmpeg_bin())
    if not ff.exists():
        raise RuntimeError(f'ffmpeg binary not found: {ff}')
    run_ffmpeg(['-version'])

    provided = [args.video, args.audio, args.ass]
    if any(provided) and not all(provided):
        raise ValueError('--video/--audio/--ass must be provided together')

    if all(provided):
        out = (args.out or (args.video.parent / 'ffmpeg_stage_merged.mp4')).resolve()
        merge_av_with_ass(video=args.video.resolve(), audio=args.audio.resolve(), ass=args.ass.resolve(), out=out)
        if not out.exists() or out.stat().st_size <= 0:
            raise RuntimeError('merge output not generated')
        _assert_av_streams(out)
        print(f'[OK] ffmpeg stage completed: {out}')
        return 0

    with tempfile.TemporaryDirectory(prefix='ffmpeg-stage-') as td:
        root = Path(td)
        video = root / 'video.mp4'
        audio = root / 'audio.m4a'
        ass = root / 'subtitle.ass'
        out = (args.out.resolve() if args.out else root / 'out.mp4')

        run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=24', '-t', str(args.seconds), '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)])
        run_ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=600:sample_rate=44100', '-t', str(args.seconds), '-c:a', 'aac', str(audio)])
        _write_ass(ass)

        merge_av_with_ass(video=video, audio=audio, ass=ass, out=out)
        if not out.exists() or out.stat().st_size <= 0:
            raise RuntimeError('merge output not generated')
        _assert_av_streams(out)
        print(f'[OK] ffmpeg stage completed: {out}')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
