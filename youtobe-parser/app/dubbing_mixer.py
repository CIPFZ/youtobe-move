from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

from app.audio_utils import probe_media_duration
from app.ffmpeg_tools import merge_av_with_ass, run_ffmpeg
from app.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class DubClip:
    start: float
    end: float
    wav_path: Path


@dataclass
class AlignedDubClip:
    source_start: float
    source_end: float
    start: float
    end: float
    wav_path: Path
    speed: float
    raw_duration: float
    spoken_duration: float


def wav_duration(path: Path) -> float:
    with wave.open(str(path), 'rb') as f:
        frames = f.getnframes()
        rate = f.getframerate()
    if rate <= 0:
        raise RuntimeError(f'Invalid wav sample rate: {path}')
    return frames / float(rate)


def _build_atempo_chain(speed: float) -> str:
    speed = max(0.5, speed)
    parts: list[str] = []
    while speed > 2.0:
        parts.append('atempo=2.0')
        speed /= 2.0
    parts.append(f'atempo={speed:.4f}')
    return ','.join(parts)


def _resolve_alignment_params() -> tuple[float, float, float, float, str, float]:
    max_speed = max(1.0, float(settings.dubbing_max_speed))
    min_speed = min(1.0, float(settings.dubbing_min_speed))
    crossfade = max(0.0, float(settings.dubbing_crossfade_sec))
    timing_mode = settings.dubbing_timing_mode.strip().lower()
    max_advance = max(0.0, float(settings.dubbing_max_advance_sec))
    min_gap = max(0.0, float(settings.dubbing_min_gap_sec))
    preset = settings.dubbing_preset.strip().lower()
    if preset == 'natural':
        # Natural preset: avoid speed-up artifacts and allow earlier starts.
        max_speed = min(max_speed, 1.0)
        max_advance = max(max_advance, 3.0)
        min_speed = min(min_speed, 0.80)
        min_gap = min(min_gap, 0.0)
    return max_speed, min_speed, crossfade, max_advance, timing_mode, min_gap


def align_dub_clips(clips: list[DubClip]) -> list[AlignedDubClip]:
    max_speed, min_speed, _crossfade, max_advance, timing_mode, min_gap = _resolve_alignment_params()
    out: list[AlignedDubClip] = []
    prev_end_effective = 0.0

    for idx, clip in enumerate(clips, start=1):
        target = max(0.05, clip.end - clip.start)
        raw = wav_duration(clip.wav_path)
        speed = 1.0
        if not settings.dubbing_disable_time_stretch:
            if raw > target:
                speed = min(max_speed, raw / target)
            elif raw < target and raw > 0:
                speed = max(min_speed, raw / target)
        spoken = max(0.05, raw / max(0.01, speed))

        effective_start = clip.start
        if timing_mode == 'relaxed' and idx > 1:
            earliest = max(0.0, clip.start - max_advance)
            effective_start = max(earliest, prev_end_effective + min_gap)
        effective_end = effective_start + spoken

        prev_end_effective = effective_end
        out.append(
            AlignedDubClip(
                source_start=clip.start,
                source_end=clip.end,
                start=effective_start,
                end=effective_end,
                wav_path=clip.wav_path,
                speed=speed,
                raw_duration=raw,
                spoken_duration=spoken,
            )
        )
    return out


def render_dub_voice_track(
    clips: list[DubClip],
    out_path: Path,
    total_duration_sec: float | None = None,
) -> tuple[Path, list[AlignedDubClip]]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    aligned = align_dub_clips(clips)
    _max_speed, _min_speed, crossfade, _max_advance, timing_mode, _min_gap = _resolve_alignment_params()

    if total_duration_sec is None:
        max_end = max((c.end for c in aligned), default=1.0)
        total_duration_sec = max(1.0, max_end + 0.1)

    args: list[str] = [
        '-f',
        'lavfi',
        '-i',
        f'anullsrc=channel_layout=stereo:sample_rate=44100:d={total_duration_sec:.3f}',
    ]
    chains: list[str] = []
    mix_inputs = ['[0:a]']

    for idx, clip in enumerate(aligned, start=1):
        args.extend(['-i', str(clip.wav_path)])
        delay_ms = max(0, int(round(clip.start * 1000)))
        source = f'[{idx}:a]'
        chain = _build_atempo_chain(clip.speed)
        trim = f'atrim=0:{clip.spoken_duration + crossfade:.3f}'
        label = f'[c{idx}]'
        chains.append(f'{source}{chain},{trim},adelay={delay_ms}|{delay_ms}{label}')
        mix_inputs.append(label)
        logger.info(
            'Dub clip aligned. idx=%d src=[%.3f,%.3f] raw=%.3fs speed=%.3f out=[%.3f,%.3f] mode=%s',
            idx,
            clip.source_start,
            clip.source_end,
            clip.raw_duration,
            clip.speed,
            clip.start,
            clip.end,
            timing_mode,
        )

    num_inputs = len(mix_inputs)
    mix = ''.join(mix_inputs) + f'amix=inputs={num_inputs}:normalize=0:dropout_transition=0[aout]'
    filter_complex = ';'.join(chains + [mix])

    args.extend(
        [
            '-filter_complex',
            filter_complex,
            '-map',
            '[aout]',
            '-c:a',
            'pcm_s16le',
            str(out_path),
        ]
    )
    run_ffmpeg(args)
    return out_path, aligned


def mix_voice_with_bgm(voice_wav: Path, bgm_wav: Path, out_audio_path: Path) -> Path:
    out_audio_path.parent.mkdir(parents=True, exist_ok=True)
    bgm_volume = float(settings.dubbing_bgm_volume)
    voice_volume = float(settings.dubbing_voice_volume)
    run_ffmpeg(
        [
            '-i',
            str(bgm_wav),
            '-i',
            str(voice_wav),
            '-filter_complex',
            (
                f'[0:a]volume={bgm_volume:.3f}[bgm];'
                f'[1:a]volume={voice_volume:.3f}[voice];'
                '[bgm][voice]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[mix]'
            ),
            '-map',
            '[mix]',
            '-c:a',
            'aac',
            '-b:a',
            '192k',
            str(out_audio_path),
        ]
    )
    return out_audio_path


def compose_dubbed_video(video_path: Path, mixed_audio_path: Path, ass_path: Path, out_path: Path) -> Path:
    merge_av_with_ass(video=video_path, audio=mixed_audio_path, ass=ass_path, out=out_path)
    return out_path


def media_duration(path: Path) -> float:
    duration = probe_media_duration(path)
    return max(duration, 1.0)
