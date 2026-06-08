from __future__ import annotations

import logging
import re
import wave
from pathlib import Path

import numpy as np

from app.audio_separation import separate_vocals_with_demucs
from app.dubbing_mixer import AlignedDubClip, DubClip, compose_dubbed_video, media_duration, mix_voice_with_bgm, render_dub_voice_track
from app.dubbing_segments import DubbingSegment, build_semantic_segments, estimate_chars_per_sec
from app.settings import settings
from app.srt_tools import read_srt
from app.subtitles import Segment, write_ass
from app.translator import SubtitleTranslator
from app.tts_engine import create_tts_engine

logger = logging.getLogger(__name__)


class DubbingPipeline:
    def __init__(self) -> None:
        self.work_dir = settings.work_dir.resolve() / settings.dubbing_work_dirname
        self.sep_dir = self.work_dir / 'separated'
        self.tts_dir = self.work_dir / 'tts_segments'
        self.audio_dir = self.work_dir / 'audio'
        self.subtitle_dir = self.work_dir / 'subtitles'
        self.output_dir = self.work_dir / 'output'
        for d in (self.sep_dir, self.tts_dir, self.audio_dir, self.subtitle_dir, self.output_dir):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _split_cn_clauses(text: str) -> list[str]:
        cleaned = ''.join(text.split())
        if not cleaned:
            return []
        parts = re.split(r'([，。！？；：,.!?;:])', cleaned)
        out: list[str] = []
        i = 0
        while i < len(parts):
            body = (parts[i] or '').strip()
            punct = parts[i + 1] if i + 1 < len(parts) else ''
            if body:
                out.append(f'{body}{punct}'.strip())
            i += 2
        return out or [cleaned]

    @staticmethod
    def _reflow_zh_subtitles(translated: list[DubbingSegment], aligned: list[AlignedDubClip]) -> list[Segment]:
        if len(translated) != len(aligned):
            raise ValueError('translated and aligned clips length mismatch')
        if not settings.dubbing_reflow_subtitles:
            out: list[Segment] = []
            for seg, clip in zip(translated, aligned):
                text = (seg.translated_text or seg.source_text).strip()
                if not text:
                    continue
                out.append(Segment(start=clip.start, end=clip.end, text=text))
            return out

        timed_clauses: list[Segment] = []
        for seg, clip in zip(translated, aligned):
            text = (seg.translated_text or seg.source_text).strip()
            if not text:
                continue
            clauses = DubbingPipeline._split_cn_clauses(text)
            total_weight = sum(max(1, len(c)) for c in clauses)
            cursor = clip.start
            span = max(0.05, clip.end - clip.start)
            for idx, clause in enumerate(clauses):
                weight = max(1, len(clause))
                if idx == len(clauses) - 1:
                    end = clip.end
                else:
                    end = cursor + span * (weight / max(1, total_weight))
                end = max(end, cursor + 0.05)
                timed_clauses.append(Segment(start=cursor, end=end, text=clause))
                cursor = end

        if not timed_clauses:
            return []

        # Re-pack timed clauses into readable subtitle chunks.
        max_chars = max(8, int(settings.dubbing_subtitle_max_chars))
        max_duration = max(1.2, float(settings.dubbing_subtitle_max_duration_sec))
        max_gap = max(0.0, float(settings.dubbing_subtitle_max_gap_sec))
        repacked: list[Segment] = []

        cur_start = timed_clauses[0].start
        cur_end = timed_clauses[0].end
        cur_text = timed_clauses[0].text

        for seg in timed_clauses[1:]:
            cand_text = f'{cur_text}{seg.text}'
            cand_duration = seg.end - cur_start
            gap = max(0.0, seg.start - cur_end)
            if len(cand_text) <= max_chars and cand_duration <= max_duration and gap <= max_gap:
                cur_text = cand_text
                cur_end = max(cur_end, seg.end)
                continue
            repacked.append(Segment(start=cur_start, end=cur_end, text=cur_text))
            cur_start, cur_end, cur_text = seg.start, seg.end, seg.text

        repacked.append(Segment(start=cur_start, end=cur_end, text=cur_text))
        return repacked

    @staticmethod
    def _write_mono_ass_from_aligned(
        translated: list[DubbingSegment],
        aligned: list[AlignedDubClip],
        output_ass: Path,
    ) -> Path:
        segments = DubbingPipeline._reflow_zh_subtitles(translated, aligned)
        write_ass(segments, output_ass)
        return output_ass

    def _translate_for_dub(self, items: list[DubbingSegment]) -> list[DubbingSegment]:
        src = [Segment(start=s.start, end=s.end, text=s.source_text) for s in items]
        translated = SubtitleTranslator(target_language=settings.dub_target_language).translate(src)
        out: list[DubbingSegment] = []
        max_cps = float(settings.dubbing_max_chars_per_sec)
        for seg, tr in zip(items, translated):
            zh = tr.text.strip()
            cps = estimate_chars_per_sec(zh, seg.duration)
            if (not settings.dubbing_preserve_full_text) and cps > max_cps:
                # Keep first iteration deterministic: limit over-long Chinese text by simple truncation.
                cap = max(4, int(seg.duration * max_cps))
                zh = ''.join(ch for ch in zh if not ch.isspace())[:cap]
            out.append(DubbingSegment(id=seg.id, start=seg.start, end=seg.end, source_text=seg.source_text, translated_text=zh))
        return out

    def _tts_segments(self, items: list[DubbingSegment], stem: str) -> list[DubClip]:
        tts = create_tts_engine()
        clips: list[DubClip] = []
        for seg in items:
            text = seg.translated_text.strip() or seg.source_text.strip()
            out = self.tts_dir / stem / f'seg_{seg.id:04d}.wav'
            tts.synthesize_to_wav(text=text, out_path=out)
            self._trim_tts_wav_silence(out)
            clips.append(DubClip(start=seg.start, end=seg.end, wav_path=out))
        return clips

    @staticmethod
    def _trim_tts_wav_silence(path: Path) -> None:
        if not settings.dubbing_trim_tts_silence or not path.exists():
            return
        try:
            with wave.open(str(path), 'rb') as wf:
                n_channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)
        except wave.Error:
            logger.warning('Skip TTS silence trim for invalid wav file: %s', path)
            return
        if sample_width != 2 or n_frames <= 0:
            return

        pcm = np.frombuffer(raw, dtype=np.int16)
        if n_channels > 1:
            if pcm.size % n_channels != 0:
                return
            mono = np.abs(pcm.reshape(-1, n_channels).mean(axis=1) / 32768.0)
        else:
            mono = np.abs(pcm.astype(np.float32) / 32768.0)

        threshold = max(0.001, float(settings.dubbing_tts_silence_threshold))
        active_idx = np.where(mono >= threshold)[0]
        if active_idx.size == 0:
            return

        keep_lead = max(0.0, float(settings.dubbing_tts_keep_lead_sec))
        keep_tail = max(0.0, float(settings.dubbing_tts_keep_tail_sec))
        lead_frames = int(round(keep_lead * sample_rate))
        tail_frames = int(round(keep_tail * sample_rate))

        start_frame = max(0, int(active_idx[0]) - lead_frames)
        end_frame = min(int(n_frames), int(active_idx[-1]) + 1 + tail_frames)
        if end_frame <= start_frame:
            return
        if start_frame == 0 and end_frame >= n_frames:
            return

        if n_channels > 1:
            shaped = pcm.reshape(-1, n_channels)[start_frame:end_frame]
        else:
            shaped = pcm[start_frame:end_frame]

        with wave.open(str(path), 'wb') as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(sample_rate)
            wf.writeframes(shaped.astype(np.int16).tobytes())

    def run(
        self,
        video_path: Path,
        audio_path: Path,
        srt_path: Path,
        ass_path: Path,
        stem: str | None = None,
        separated_pair: tuple[Path, Path] | None = None,
    ) -> Path:
        for p in (video_path, audio_path, srt_path, ass_path):
            if not p.exists():
                raise FileNotFoundError(f'Input file not found: {p}')
        stem = stem or video_path.stem
        logger.info('Dubbing pipeline started. stem=%s', stem)

        logger.info('Stage 5/8: separate vocals and accompaniment')
        if separated_pair is not None:
            vocals_en, bgm = separated_pair
            if not vocals_en.exists() or not bgm.exists():
                raise FileNotFoundError(f'Invalid separated_pair: vocals={vocals_en} bgm={bgm}')
            logger.info('Reuse pre-separated stems. vocals=%s bgm=%s', vocals_en, bgm)
        else:
            vocals_en, bgm = separate_vocals_with_demucs(audio_path=audio_path, out_dir=self.sep_dir / stem)
        logger.info('Separation done. vocals=%s bgm=%s', vocals_en, bgm)

        logger.info('Stage 6/8: build semantic segments and translate to %s', settings.dub_target_language)
        srt_segments = read_srt(srt_path)
        semantic_segments = build_semantic_segments(srt_segments)
        translated = self._translate_for_dub(semantic_segments)
        logger.info('Translation for dubbing done. semantic_segments=%d', len(translated))

        logger.info('Stage 7/8: synthesize TTS and align into dub voice track')
        clips = self._tts_segments(translated, stem=stem)
        total_duration = media_duration(audio_path)
        dub_voice = self.audio_dir / f'{stem}.zh_voice.wav'
        _, aligned = render_dub_voice_track(clips=clips, out_path=dub_voice, total_duration_sec=total_duration)
        logger.info('Dub voice rendered. path=%s', dub_voice)

        logger.info('Stage 8/8: mix dub voice + bgm and compose final video')
        mixed = self.audio_dir / f'{stem}.dub_mix.m4a'
        mix_voice_with_bgm(voice_wav=dub_voice, bgm_wav=bgm, out_audio_path=mixed)
        mono_ass = self.subtitle_dir / f'{stem}.dub.ass'
        self._write_mono_ass_from_aligned(translated, aligned, mono_ass)
        out_video = self.output_dir / f'{stem}.dubbed.mp4'
        compose_dubbed_video(video_path=video_path, mixed_audio_path=mixed, ass_path=mono_ass, out_path=out_video)
        logger.info('Dubbing pipeline completed. output=%s', out_video)
        return out_video
