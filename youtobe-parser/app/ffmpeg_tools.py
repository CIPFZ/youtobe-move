from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

import imageio_ffmpeg

from app.settings import settings

logger = logging.getLogger(__name__)


_AV1_DECODER_ERRORS = (
    'Decoder (codec av1) not found',
    'decoder for codec id 32797 not found',
)


def _all_ffmpeg_candidates() -> list[str]:
    custom = settings.ffmpeg_path.strip()
    if custom:
        p = Path(custom).expanduser()
        if p.exists() and p.is_file():
            return [str(p)]
        raise FileNotFoundError(f'Configured FFMPEG_PATH does not exist: {custom}')

    cands: list[str] = []
    system_ffmpeg = shutil.which('ffmpeg')
    if system_ffmpeg:
        cands.append(system_ffmpeg)

    imageio_bin = imageio_ffmpeg.get_ffmpeg_exe()
    if imageio_bin not in cands:
        cands.append(imageio_bin)
    return cands


def ffmpeg_bin() -> str:
    """Resolve ffmpeg binary path.

    Priority:
    1) FFMPEG_PATH from settings (.env / env var)
    2) PATH lookup for "ffmpeg"
    3) imageio-ffmpeg managed binary
    """
    chosen = _all_ffmpeg_candidates()[0]
    logger.info('Using ffmpeg binary: %s', chosen)
    return chosen


def _run_cmd_with_binary(bin_path: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = [bin_path, '-y', *args]
    logger.info('Running ffmpeg command: %s', ' '.join(cmd))
    return subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def run_ffmpeg(args: list[str]) -> None:
    candidates = _all_ffmpeg_candidates()
    first_bin = candidates[0]
    proc = _run_cmd_with_binary(first_bin, args)
    if proc.returncode == 0:
        return

    # Fallback: retry with secondary ffmpeg (usually imageio-managed binary) when available.
    # This handles AV1 decoder gaps and broken system/snap ffmpeg builds.
    if len(candidates) > 1:
        fallback_bin = candidates[1]
        logger.warning(
            'Primary ffmpeg failed, retrying with fallback binary. '
            'primary=%s fallback=%s',
            first_bin,
            fallback_bin,
        )
        proc2 = _run_cmd_with_binary(fallback_bin, args)
        if proc2.returncode == 0:
            return
        raise subprocess.CalledProcessError(proc2.returncode, [fallback_bin, '-y', *args], output=proc2.stdout, stderr=proc2.stderr)

    raise subprocess.CalledProcessError(proc.returncode, [first_bin, '-y', *args], output=proc.stdout, stderr=proc.stderr)


def merge_av_with_ass(video: Path, audio: Path, ass: Path, out: Path) -> None:
    logger.info('Merging A/V with subtitles. video=%s audio=%s ass=%s out=%s', video, audio, ass, out)
    run_ffmpeg(
        [
            '-i', str(video),
            '-i', str(audio),
            '-vf', f'ass={ass.as_posix()}',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-shortest',
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-crf', '20',
            '-c:a', 'aac',
            '-b:a', '192k',
            str(out),
        ]
    )
