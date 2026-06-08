from __future__ import annotations

import logging
import os
from pathlib import Path

from faster_whisper import WhisperModel

from app.settings import settings
from app.subtitles import Segment

logger = logging.getLogger(__name__)


def _apply_download_proxy_env(proxy_url: str) -> None:
    if not proxy_url:
        return

    if proxy_url.lower().startswith('socks'):
        try:
            import socksio  # noqa: F401
        except Exception as exc:
            raise RuntimeError(
                'SOCKS proxy detected but dependency `socksio` is missing. '
                'Please run: pip install socksio'
            ) from exc

    os.environ['HTTP_PROXY'] = proxy_url
    os.environ['HTTPS_PROXY'] = proxy_url
    os.environ['ALL_PROXY'] = proxy_url
    logger.info('Applied whisper download proxy via env: %s', proxy_url)


def _auto_select_device(requested_device: str) -> str:
    device = requested_device.strip().lower()
    if device != 'auto':
        return device
    try:
        import ctranslate2

        cuda_count = ctranslate2.get_cuda_device_count()
        chosen = 'cuda' if cuda_count > 0 else 'cpu'
        logger.info('Auto-selected whisper device: %s (cuda_count=%s)', chosen, cuda_count)
        return chosen
    except Exception as exc:
        logger.warning('Failed to detect CUDA device count, fallback to cpu. err=%s', exc)
        return 'cpu'


def _auto_select_compute_type(requested_compute_type: str, device: str) -> str:
    compute_type = requested_compute_type.strip().lower()
    if compute_type != 'auto':
        return compute_type
    chosen = 'float16' if device == 'cuda' else 'int8'
    logger.info('Auto-selected whisper compute_type: %s for device=%s', chosen, device)
    return chosen


def _download_huggingface_model_to_local(model_ref: str, cache_dir: Path) -> str:
    """Download fast-whisper model from HF and return local directory path."""
    from faster_whisper.utils import download_model

    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info('Downloading whisper model from HuggingFace. model=%s cache_dir=%s', model_ref, cache_dir)
    local_dir = download_model(model_ref, output_dir=str(cache_dir))
    logger.info('HuggingFace model ready: %s', local_dir)
    return str(local_dir)


def _resolve_whisper_model_ref(source: str | None = None) -> str:
    """Resolve faster-whisper model ref/path based on configured source."""
    source = (source or settings.whisper_model_source).strip().lower()
    model_ref = settings.whisper_model.strip()

    # local path always wins
    if model_ref and Path(model_ref).expanduser().exists():
        local_path = str(Path(model_ref).expanduser())
        logger.info('Using local whisper model path: %s', local_path)
        return local_path

    if source == 'huggingface':
        if settings.whisper_download_to_local:
            cache_dir = settings.whisper_model_cache_dir.expanduser().resolve()
            return _download_huggingface_model_to_local(model_ref, cache_dir)
        return model_ref

    if source == 'modelscope':
        repo_id = settings.whisper_modelscope_repo.strip()
        if not repo_id:
            raise ValueError('WHISPER_MODELSCOPE_REPO is required when WHISPER_MODEL_SOURCE=modelscope')
        try:
            from modelscope.hub.snapshot_download import snapshot_download
        except Exception as exc:
            raise RuntimeError(
                'ModelScope support requires `modelscope` package. Please install it first.'
            ) from exc

        cache_dir = settings.whisper_model_cache_dir.expanduser().resolve()
        cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info('Downloading whisper model from ModelScope. repo=%s cache_dir=%s', repo_id, cache_dir)
        local_dir = snapshot_download(repo_id, cache_dir=str(cache_dir))
        logger.info('ModelScope model ready: %s', local_dir)
        return str(local_dir)

    raise ValueError('WHISPER_MODEL_SOURCE must be one of: huggingface, modelscope')


class FastWhisperTranscriber:
    def __init__(self) -> None:
        source = settings.whisper_model_source.strip().lower()
        _apply_download_proxy_env(settings.whisper_download_proxy.strip())

        resolved_model = _resolve_whisper_model_ref(source=source)
        resolved_device = _auto_select_device(settings.whisper_device)
        resolved_compute_type = _auto_select_compute_type(settings.whisper_compute_type, resolved_device)
        logger.info(
            'Loading faster-whisper model. source=%s model_ref=%s resolved=%s device=%s compute_type=%s',
            settings.whisper_model_source,
            settings.whisper_model,
            resolved_model,
            resolved_device,
            resolved_compute_type,
        )
        try:
            self.model = WhisperModel(
                resolved_model,
                device=resolved_device,
                compute_type=resolved_compute_type,
            )
        except Exception as exc:
            msg = str(exc).lower()
            if resolved_device == 'cuda' and ('out of memory' in msg or 'cuda failed' in msg):
                logger.warning('Whisper CUDA load OOM, fallback to cpu/int8. err=%s', exc)
                self.model = WhisperModel(
                    resolved_model,
                    device='cpu',
                    compute_type='int8',
                )
                logger.info('Loaded whisper model with CPU fallback after CUDA OOM.')
                return
            if (
                source == 'huggingface'
                and settings.whisper_model_fallback_to_modelscope
                and settings.whisper_modelscope_repo.strip()
            ):
                logger.warning('HuggingFace model load failed, fallback to ModelScope is enabled. err=%s', exc)
                ms_model = _resolve_whisper_model_ref(source='modelscope')
                self.model = WhisperModel(
                    ms_model,
                    device=resolved_device,
                    compute_type=resolved_compute_type,
                )
                logger.info('Loaded whisper model from ModelScope fallback. path=%s', ms_model)
            else:
                raise RuntimeError(
                    'Whisper model load failed. If HuggingFace is unreachable, set '
                    'WHISPER_MODEL_SOURCE=modelscope and WHISPER_MODELSCOPE_REPO, '
                    'or configure WHISPER_DOWNLOAD_PROXY.'
                ) from exc

    def transcribe(self, audio_path: str) -> list[Segment]:
        logger.info('Transcription started. audio=%s language=%s', audio_path, settings.whisper_language)
        segments, _info = self.model.transcribe(audio_path, language=settings.whisper_language, vad_filter=True)
        result = [Segment(start=s.start, end=s.end, text=s.text) for s in segments]
        logger.info('Transcription completed. segments=%d', len(result))
        return result
