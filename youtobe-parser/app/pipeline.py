from __future__ import annotations

import json
import logging
import gc
from dataclasses import dataclass
from pathlib import Path

from app.audio_separation import separate_vocals_with_demucs
from app.dubbing_pipeline import DubbingPipeline
from app.downloader import download_media
from app.ffmpeg_tools import merge_av_with_ass
from app.settings import settings
from app.subtitles import make_bilingual_segments, write_ass, write_srt
from app.transcriber import FastWhisperTranscriber
from app.translator import SubtitleTranslator

logger = logging.getLogger(__name__)

try:
    import torch
except Exception:  # pragma: no cover
    torch = None


@dataclass(frozen=True)
class PipelineOutputs:
    bilingual_video: Path
    dubbed_video: Path | None
    srt_path: Path
    ass_path: Path
    video_path: Path
    audio_path: Path
    stem: str


class Pipeline:
    def __init__(self) -> None:
        self.work_dir = settings.work_dir.resolve()
        self.download_dir = self.work_dir / 'downloads'
        self.subtitle_dir = self.work_dir / 'subtitles'
        self.output_dir = self.work_dir / 'output'
        self.metadata_dir = self.work_dir / settings.metadata_dirname
        self.transcribe_sep_dir = self.work_dir / settings.transcribe_separation_dirname
        for d in (self.download_dir, self.subtitle_dir, self.output_dir, self.metadata_dir, self.transcribe_sep_dir):
            d.mkdir(parents=True, exist_ok=True)
        logger.info('Pipeline initialized. work_dir=%s', self.work_dir)

    @staticmethod
    def _artifact_stem(media: dict) -> str:
        metadata = media.get('metadata') or {}
        video_id = str(metadata.get('id') or '').strip()
        return video_id or settings.output_name

    def _resolve_transcription_audio(self, audio_path: Path, stem: str) -> tuple[Path, tuple[Path, Path] | None]:
        if not settings.transcribe_use_vocals:
            return audio_path, None

        sep_out = self.transcribe_sep_dir / stem
        try:
            vocals_path, bgm_path = separate_vocals_with_demucs(audio_path=audio_path, out_dir=sep_out)
            if not vocals_path.exists() or vocals_path.stat().st_size <= 0:
                raise RuntimeError(f'Invalid vocals path: {vocals_path}')
            logger.info('Transcription audio resolved to vocals stem. source=%s vocals=%s', audio_path, vocals_path)
            return vocals_path, (vocals_path, bgm_path)
        except Exception as exc:
            if settings.transcribe_vocals_fallback_to_original:
                logger.warning('Vocal-first transcription failed, fallback to original audio. err=%s', exc)
                return audio_path, None
            raise

    def run_with_media(
        self,
        video_path: Path,
        audio_path: Path,
        thumbnail_path: Path | None = None,
        stem: str | None = None,
    ) -> PipelineOutputs:
        """Run full pipeline using already-downloaded media (skips Stage 1 download).

        *stem* defaults to video_path.stem if not provided.
        """
        video_path = video_path.resolve()
        audio_path = audio_path.resolve()
        for p in (video_path, audio_path):
            if not p.exists():
                raise FileNotFoundError(f'Media file not found: {p}')
        stem = stem or video_path.stem
        logger.info('Pipeline (skip-download) started. stem=%s video=%s audio=%s', stem, video_path, audio_path)

        logger.info('Stage 2/4: transcribe audio to SRT segments')
        transcribe_audio_path, separated_pair = self._resolve_transcription_audio(audio_path=audio_path, stem=stem)
        transcriber = FastWhisperTranscriber()
        segments = transcriber.transcribe(str(transcribe_audio_path))
        del transcriber
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        srt_path = self.subtitle_dir / f'{stem}.srt'
        write_srt(segments, srt_path)
        logger.info('SRT written. path=%s segments=%d transcribe_audio=%s', srt_path, len(segments), transcribe_audio_path)

        logger.info('Stage 3/4: translate segments and write bilingual ASS')
        translated = SubtitleTranslator().translate(segments)
        bilingual = make_bilingual_segments(segments, translated)
        ass_path = self.subtitle_dir / f'{stem}.ass'
        write_ass(bilingual, ass_path)
        logger.info('ASS written (bilingual). path=%s segments=%d', ass_path, len(bilingual))

        logger.info('Stage 4/4: merge video + audio + ASS')
        output_path = self.output_dir / f'{stem}.mp4'
        merge_av_with_ass(video=video_path, audio=audio_path, ass=ass_path, out=output_path)
        logger.info('Merge completed. output=%s', output_path)

        dubbed_output: Path | None = None
        if settings.pipeline_enable_dubbing:
            logger.info('Stage 5/5: run Chinese dubbing pipeline')
            dubbed_output = DubbingPipeline().run(
                video_path=video_path,
                audio_path=audio_path,
                srt_path=srt_path,
                ass_path=ass_path,
                stem=stem,
                separated_pair=separated_pair,
            )
            logger.info('Dubbing completed. output=%s', dubbed_output)
        else:
            logger.info('Dubbing stage disabled by PIPELINE_ENABLE_DUBBING=false')

        return PipelineOutputs(
            bilingual_video=output_path,
            dubbed_video=dubbed_output,
            srt_path=srt_path,
            ass_path=ass_path,
            video_path=video_path,
            audio_path=audio_path,
            stem=stem,
        )

    def run(self, url: str) -> PipelineOutputs:
        logger.info('Stage 1/4: parse and download media')
        media = download_media(
            url=url,
            out_dir=self.download_dir,
            cookie_file=settings.cookie_file,
            proxy_url=settings.ytdlp_proxy,
            playlist_strategy=settings.playlist_strategy,
        )
        video_path = Path(media['video_path'])
        audio_path = Path(media['audio_path'])
        stem = self._artifact_stem(media)
        logger.info('Downloaded media. video=%s audio=%s stem=%s', video_path, audio_path, stem)

        metadata_path = self.metadata_dir / f'{stem}.video_info.json'
        metadata_path.write_text(json.dumps(media.get('metadata', {}), ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info('Video metadata written. path=%s', metadata_path)

        logger.info('Stage 2/4: transcribe audio to SRT segments')
        transcribe_audio_path, separated_pair = self._resolve_transcription_audio(audio_path=audio_path, stem=stem)
        transcriber = FastWhisperTranscriber()
        segments = transcriber.transcribe(str(transcribe_audio_path))
        del transcriber
        gc.collect()
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        srt_path = self.subtitle_dir / f'{stem}.srt'
        write_srt(segments, srt_path)
        logger.info('SRT written. path=%s segments=%d transcribe_audio=%s', srt_path, len(segments), transcribe_audio_path)

        logger.info('Stage 3/4: translate segments and write bilingual ASS')
        translated = SubtitleTranslator().translate(segments)
        bilingual = make_bilingual_segments(segments, translated)
        ass_path = self.subtitle_dir / f'{stem}.ass'
        write_ass(bilingual, ass_path)
        logger.info('ASS written (bilingual). path=%s segments=%d', ass_path, len(bilingual))

        logger.info('Stage 4/4: merge video + audio + ASS')
        output_path = self.output_dir / f'{stem}.mp4'
        merge_av_with_ass(video=video_path, audio=audio_path, ass=ass_path, out=output_path)
        logger.info('Merge completed. output=%s', output_path)

        dubbed_output: Path | None = None
        if settings.pipeline_enable_dubbing:
            logger.info('Stage 5/5: run Chinese dubbing pipeline')
            dubbed_output = DubbingPipeline().run(
                video_path=video_path,
                audio_path=audio_path,
                srt_path=srt_path,
                ass_path=ass_path,
                stem=stem,
                separated_pair=separated_pair,
            )
            logger.info('Dubbing completed. output=%s', dubbed_output)
        else:
            logger.info('Dubbing stage disabled by PIPELINE_ENABLE_DUBBING=false')

        return PipelineOutputs(
            bilingual_video=output_path,
            dubbed_video=dubbed_output,
            srt_path=srt_path,
            ass_path=ass_path,
            video_path=video_path,
            audio_path=audio_path,
            stem=stem,
        )
