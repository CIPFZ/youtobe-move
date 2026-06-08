from __future__ import annotations

import gc
import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import torch
import torch.hub
from demucs.apply import apply_model
from demucs.pretrained import get_model

from app.ffmpeg_tools import ffmpeg_bin
from app.settings import settings

logger = logging.getLogger(__name__)


def _demucs_cache_root() -> Path:
    return settings.demucs_cache_dir.expanduser().resolve()


def _demucs_torch_home() -> Path:
    return (_demucs_cache_root() / 'torch').resolve()


def _demucs_hub_dir() -> Path:
    return (_demucs_torch_home() / 'hub').resolve()


def _prepare_demucs_hub_dir() -> Path:
    hub_dir = _demucs_hub_dir()
    hub_dir.mkdir(parents=True, exist_ok=True)
    torch.hub.set_dir(str(hub_dir))
    return hub_dir


def _resolve_demucs_device() -> str:
    dev = settings.demucs_device.strip().lower()
    if dev in {'cpu', 'cuda'}:
        return dev
    if torch.cuda.is_available():
        logger.info('Demucs auto device resolved to cuda (torch.cuda.is_available=True)')
        return 'cuda'
    if shutil.which('nvidia-smi'):
        logger.info('Demucs auto device resolved to cuda (nvidia-smi found)')
        return 'cuda'
    logger.info('Demucs auto device resolved to cpu')
    return 'cpu'


def _resolve_runtime_device(device: str) -> str:
    if device == 'cuda' and not torch.cuda.is_available():
        logger.warning('DEMUCS_DEVICE resolved to cuda but cuda is not available at runtime, fallback to cpu')
        return 'cpu'
    return device


def predownload_demucs_model(cache_out_dir: Path | None = None) -> Path:
    model_name = settings.demucs_model.strip() or 'htdemucs_ft'
    device = _resolve_demucs_device()
    hub_dir = _prepare_demucs_hub_dir()
    get_model(model_name)

    out_root = (cache_out_dir or _demucs_cache_root()).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    marker = out_root / f'demucs_{model_name}_ready.txt'
    marker.write_text(
        f'model={model_name}\ndevice={device}\ntorch_hub={hub_dir}\n',
        encoding='utf-8',
    )
    return marker


def _decode_audio_to_tensor(path: Path, sample_rate: int, channels: int) -> torch.Tensor:
    cmd = [
        ffmpeg_bin(),
        '-v',
        'error',
        '-i',
        str(path),
        '-f',
        'f32le',
        '-acodec',
        'pcm_f32le',
        '-ac',
        str(channels),
        '-ar',
        str(sample_rate),
        '-',
    ]
    proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError(f'Failed to decode audio via ffmpeg: {proc.stderr.decode("utf-8", errors="ignore")}')
    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    if samples.size == 0:
        raise RuntimeError(f'Decoded audio is empty: {path}')
    if samples.size % channels != 0:
        raise RuntimeError(f'Decoded PCM sample size is invalid for channels={channels}: {samples.size}')
    wav = samples.reshape(-1, channels).T
    return torch.from_numpy(wav.copy())


def _write_wav_pcm16(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    # audio shape: [channels, samples], float32 in [-1, 1]
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped.T * 32767.0).astype(np.int16)
    channels = int(pcm16.shape[1]) if pcm16.ndim == 2 else 1
    cmd = [
        ffmpeg_bin(),
        '-v',
        'error',
        '-f',
        's16le',
        '-ar',
        str(sample_rate),
        '-ac',
        str(channels),
        '-i',
        '-',
        '-y',
        str(path),
    ]
    proc = subprocess.run(cmd, input=pcm16.tobytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f'Failed to write wav via ffmpeg: {proc.stderr.decode("utf-8", errors="ignore")}')


def separate_vocals_with_demucs(audio_path: Path, out_dir: Path) -> tuple[Path, Path]:
    model_name = settings.demucs_model.strip() or 'htdemucs_ft'
    requested_device = _resolve_demucs_device()
    runtime_device = _resolve_runtime_device(requested_device)
    _prepare_demucs_hub_dir()

    logger.info(
        'Running vocal separation with Demucs API. model=%s device=%s audio=%s out=%s',
        model_name,
        runtime_device,
        audio_path,
        out_dir,
    )

    stem = audio_path.stem
    target_root = out_dir / model_name / stem
    vocals_path = target_root / 'vocals.wav'
    no_vocals_path = target_root / 'no_vocals.wav'
    if vocals_path.exists() and no_vocals_path.exists():
        if vocals_path.stat().st_size > 0 and no_vocals_path.stat().st_size > 0:
            logger.info('Demucs separation cache hit. vocals=%s bgm=%s', vocals_path, no_vocals_path)
            return vocals_path, no_vocals_path

    def _run_once(device: str) -> tuple[Path, Path]:
        model = None
        mix = None
        pred = None
        try:
            model = get_model(model_name)
            model.to(device)
            model.eval()

            sample_rate = int(getattr(model, 'samplerate', 44100))
            channels = int(getattr(model, 'audio_channels', 2))
            sources = list(getattr(model, 'sources', ['drums', 'bass', 'other', 'vocals']))
            if 'vocals' not in sources:
                raise RuntimeError(f'Demucs model sources do not include vocals: {sources}')
            vocals_idx = sources.index('vocals')

            mix = _decode_audio_to_tensor(audio_path, sample_rate=sample_rate, channels=channels).unsqueeze(0)
            mix = mix.to(device)

            with torch.no_grad():
                pred = apply_model(model, mix, device=device, split=True, overlap=0.25, shifts=1, progress=False)
            # pred shape: [batch=1, sources, channels, samples]
            pred_np = pred[0].detach().cpu().numpy()
            mix_np = mix[0].detach().cpu().numpy()
            vocals = pred_np[vocals_idx]
            no_vocals = mix_np - vocals

            _write_wav_pcm16(vocals_path, vocals, sample_rate=sample_rate)
            _write_wav_pcm16(no_vocals_path, no_vocals, sample_rate=sample_rate)
            return vocals_path, no_vocals_path
        finally:
            del pred
            del mix
            del model
            gc.collect()
            if device == 'cuda' and torch.cuda.is_available():
                torch.cuda.empty_cache()

    try:
        return _run_once(runtime_device)
    except torch.OutOfMemoryError as exc:
        if runtime_device == 'cuda' and settings.demucs_cuda_fallback_to_cpu:
            logger.warning('Demucs CUDA OOM, fallback to CPU. err=%s', exc)
            return _run_once('cpu')
        raise
