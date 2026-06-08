#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from unittest import mock

from app.dubbing_pipeline import DubbingPipeline
from app.ffmpeg_tools import run_ffmpeg


def _build_inputs(work_dir: Path) -> tuple[Path, Path, Path, Path]:
    video = work_dir / 'video.mp4'
    audio = work_dir / 'audio.m4a'
    srt = work_dir / 'sub.srt'
    ass = work_dir / 'sub.ass'

    run_ffmpeg(['-f', 'lavfi', '-i', 'testsrc=size=640x360:rate=24', '-t', '2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)])
    run_ffmpeg(['-f', 'lavfi', '-i', 'sine=frequency=500:sample_rate=44100', '-t', '2', '-c:a', 'aac', str(audio)])
    srt.write_text(
        '1\n00:00:00,000 --> 00:00:01,000\nhello world\n\n'
        '2\n00:00:01,000 --> 00:00:02,000\nthis is a test\n',
        encoding='utf-8',
    )
    ass.write_text(
        '[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\n'
        'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
        'Style: Default,Arial,40,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2.8,0,2,36,36,40,1\n\n'
        '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
        'Dialogue: 0,0:00:00.00,0:00:02.00,Default,,0,0,0,,test\n',
        encoding='utf-8',
    )
    return video, audio, srt, ass


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Dubbing pipeline stage check.')
    p.add_argument('--run-real', action='store_true', help='Run real Demucs + TTS. Otherwise run mock wiring test.')
    return p.parse_args()


def _run_mock_mode(video: Path, audio: Path, srt: Path, ass: Path) -> Path:
    tmp_root = video.parent
    fake_vocals = tmp_root / 'vocals.wav'
    fake_bgm = tmp_root / 'bgm.wav'
    fake_vocals.write_bytes(b'RIFF0000WAVE')
    fake_bgm.write_bytes(b'RIFF0000WAVE')

    def _write_dummy(path: Path, payload: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    with (
        mock.patch('app.dubbing_pipeline.separate_vocals_with_demucs', return_value=(fake_vocals, fake_bgm)),
        mock.patch('app.dubbing_pipeline.create_tts_engine') as mock_tts_factory,
        mock.patch('app.dubbing_pipeline.render_dub_voice_track') as mock_render,
        mock.patch('app.dubbing_pipeline.mix_voice_with_bgm') as mock_mix,
        mock.patch('app.dubbing_pipeline.compose_dubbed_video') as mock_compose,
    ):
        mock_tts = mock.Mock()
        mock_tts.synthesize_to_wav.side_effect = lambda text, out_path: _write_dummy(out_path, b'RIFF0000WAVE')
        mock_tts_factory.return_value = mock_tts
        mock_render.side_effect = lambda clips, out_path, total_duration_sec: _write_dummy(out_path, b'RIFF0000WAVE')
        mock_mix.side_effect = lambda voice_wav, bgm_wav, out_audio_path: _write_dummy(out_audio_path, b'\x00')
        mock_compose.side_effect = lambda video_path, mixed_audio_path, ass_path, out_path: _write_dummy(out_path, b'\x00')

        out = DubbingPipeline().run(video_path=video, audio_path=audio, srt_path=srt, ass_path=ass, stem='mock_case')
        if not out.exists():
            raise RuntimeError('mock dubbing pipeline output not generated')
        return out


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix='dubbing-stage-') as td:
        root = Path(td)
        video, audio, srt, ass = _build_inputs(root)
        if not args.run_real:
            out = _run_mock_mode(video, audio, srt, ass)
            print(f'[OK] dubbing stage mock completed: {out}')
            return 0

        out = DubbingPipeline().run(video_path=video, audio_path=audio, srt_path=srt, ass_path=ass, stem='real_case')
        print(f'[OK] dubbing stage real completed: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
