#!/usr/bin/env python3
from __future__ import annotations

"""Real integration test: merge ASS + audio + video into final mp4.

Usage examples:
  python -m tests.test_merge_ass_audio_video
  python -m tests.test_merge_ass_audio_video -- --video ./in.mp4 --audio ./in.m4a --ass ./sub.ass --out ./merged.mp4
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

from app.ffmpeg_tools import ffmpeg_bin, merge_av_with_ass, run_ffmpeg
from app.logging_utils import setup_logging
from app.settings import settings


def _write_ass(path: Path) -> None:
    path.write_text(
        """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,42,&H00FFFFFF,&H0000FFFF,&H00000000,&H55000000,-1,0,0,0,100,100,0,0,1,2,0,2,30,30,26,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:02.50,Default,,0,0,0,,merge test subtitle
""",
        encoding='utf-8',
    )


def _assert_has_av_streams(path: Path) -> None:
    proc = subprocess.run(
        [ffmpeg_bin(), '-i', str(path), '-f', 'null', '-'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    report = proc.stderr
    if 'Video:' not in report or 'Audio:' not in report:
        raise RuntimeError(f'output does not contain both audio and video streams:\n{report}')


def _build_synthetic_inputs(work_dir: Path) -> tuple[Path, Path, Path, Path]:
    video = work_dir / 'video.mp4'
    audio = work_dir / 'audio.m4a'
    ass = work_dir / 'subtitle.ass'
    out = work_dir / 'merged.mp4'

    run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc=size=1280x720:rate=30', '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)])
    run_ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=44100', '-t', '3', '-c:a', 'aac', '-b:a', '128k', str(audio)])
    _write_ass(ass)
    return video, audio, ass, out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Real ASS + video + audio merge test')
    parser.add_argument('--video', type=Path, help='input video file path')
    parser.add_argument('--audio', type=Path, help='input audio file path')
    parser.add_argument('--ass', type=Path, help='input ASS subtitle file path')
    parser.add_argument('--out', type=Path, help='output mp4 file path')
    return parser.parse_args()


def main() -> int:
    setup_logging(settings.log_level, settings.log_file)
    args = parse_args()

    provided = [args.video, args.audio, args.ass]
    if any(provided) and not all(provided):
        raise ValueError('--video/--audio/--ass must be provided together')

    if all(provided):
        video = args.video.resolve()
        audio = args.audio.resolve()
        ass = args.ass.resolve()
        out = (args.out or (video.parent / 'merged.mp4')).resolve()
    else:
        with tempfile.TemporaryDirectory(prefix='merge-test-') as td:
            video, audio, ass, out = _build_synthetic_inputs(Path(td))
            merge_av_with_ass(video=video, audio=audio, ass=ass, out=out)
            if not out.exists() or out.stat().st_size == 0:
                raise RuntimeError('merged output not generated')
            _assert_has_av_streams(out)
            print(f'[OK] merged output: {out}')
            return 0

    merge_av_with_ass(video=video, audio=audio, ass=ass, out=out)
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError('merged output not generated')
    _assert_has_av_streams(out)
    print(f'[OK] merged output: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
