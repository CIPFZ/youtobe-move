from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path

from openai import OpenAI

from app.ffmpeg_tools import run_ffmpeg
from app.settings import settings

logger = logging.getLogger(__name__)


def _resolve_edge_voice() -> str:
    custom = settings.tts_edge_voice.strip()
    if custom:
        return custom
    gender = settings.tts_voice_gender.strip().lower()
    if gender == 'male':
        return settings.tts_edge_voice_male.strip() or 'zh-CN-YunxiNeural'
    return settings.tts_edge_voice_female.strip() or 'zh-CN-XiaoxiaoNeural'


class OpenAITTSEngine:
    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError('OPENAI_API_KEY is required for TTS provider=openai')
        self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url.rstrip('/'))
        logger.info('TTS engine enabled. provider=openai model=%s voice=%s', settings.tts_openai_model, settings.tts_voice)

    def synthesize_to_wav(self, text: str, out_path: Path) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with self.client.audio.speech.with_streaming_response.create(
            model=settings.tts_openai_model,
            voice=settings.tts_voice,
            input=text,
            response_format='wav',
        ) as rsp:
            rsp.stream_to_file(str(out_path))
        return out_path


class EdgeTTSEngine:
    def __init__(self) -> None:
        try:
            import edge_tts  # noqa: F401
        except Exception as exc:
            raise RuntimeError('edge-tts is required for TTS_PROVIDER=edge') from exc
        self.voice = _resolve_edge_voice()
        logger.info('TTS engine enabled. provider=edge voice=%s gender=%s', self.voice, settings.tts_voice_gender)

    def synthesize_to_wav(self, text: str, out_path: Path) -> Path:
        import edge_tts

        out_path.parent.mkdir(parents=True, exist_ok=True)
        last_err: Exception | None = None
        # Edge websocket can occasionally timeout/reset; retry improves long-run stability.
        for attempt in range(1, 4):
            try:
                with tempfile.TemporaryDirectory(prefix='edge-tts-') as td:
                    mp3_path = Path(td) / 'tts.mp3'
                    communicate = edge_tts.Communicate(text=text, voice=self.voice)
                    asyncio.run(communicate.save(str(mp3_path)))
                    run_ffmpeg(['-i', str(mp3_path), '-ar', '44100', '-ac', '2', str(out_path)])
                return out_path
            except Exception as exc:
                last_err = exc
                logger.warning('Edge TTS failed, retrying. attempt=%d/3 err=%s', attempt, exc)
                if attempt < 3:
                    time.sleep(1.2 * attempt)
        raise RuntimeError('Edge TTS failed after retries') from last_err


def create_tts_engine() -> OpenAITTSEngine | EdgeTTSEngine:
    provider = settings.tts_provider.strip().lower()
    if provider == 'openai':
        return OpenAITTSEngine()
    if provider == 'edge':
        return EdgeTTSEngine()
    raise ValueError(f'Unsupported TTS_PROVIDER={settings.tts_provider}. Supported: openai, edge')
