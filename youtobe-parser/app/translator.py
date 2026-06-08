from __future__ import annotations

import logging

from openai import OpenAI

from app.settings import settings
from app.subtitles import Segment

logger = logging.getLogger(__name__)


class SubtitleTranslator:
    def __init__(self, target_language: str | None = None) -> None:
        self.enabled = bool(settings.openai_api_key)
        self.target_language = (target_language or settings.target_language).strip()
        self.client = (
            OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url.rstrip('/'))
            if self.enabled
            else None
        )
        if self.enabled:
            logger.info('Translator enabled. model=%s target_language=%s batch_size=%s', settings.openai_model, self.target_language, settings.translation_batch_size)
        else:
            logger.warning('Translator disabled because OPENAI_API_KEY is empty. subtitles will keep original text.')

    @staticmethod
    def _render_batch_prompt(lines: list[str]) -> str:
        body = '\n'.join(f'{i}\t{line}' for i, line in enumerate(lines, start=1))
        return (
            'Translate the following subtitle lines.\n'
            'Rules:\n'
            '1) Keep the exact number of lines.\n'
            '2) Return in the same format: <index>\\t<translated_text>.\n'
            '3) Do not merge/split lines and do not add extra text.\n\n'
            f'{body}'
        )

    @staticmethod
    def _parse_batch_output(content: str, fallback: list[str]) -> list[str]:
        parsed: dict[int, str] = {}
        for raw in content.splitlines():
            line = raw.strip()
            if '\t' not in line:
                continue
            idx_str, txt = line.split('\t', 1)
            if idx_str.isdigit():
                parsed[int(idx_str)] = txt.strip()

        out: list[str] = []
        for idx, origin in enumerate(fallback, start=1):
            out.append(parsed.get(idx, origin))
        return out

    def _translate_batch(self, texts: list[str]) -> list[str]:
        rsp = self.client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.2,
            messages=[
                {'role': 'system', 'content': f'You are a subtitle translator. Translate to {self.target_language} only.'},
                {'role': 'user', 'content': self._render_batch_prompt(texts)},
            ],
        )
        content = rsp.choices[0].message.content or ''
        return self._parse_batch_output(content, texts)

    def translate(self, segments: list[Segment]) -> list[Segment]:
        if not self.enabled:
            return segments

        out: list[Segment] = []
        batch_size = max(1, int(settings.translation_batch_size))
        logger.info('Translation started. segments=%d batch_size=%d', len(segments), batch_size)

        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            inputs = [s.text.strip() for s in batch]
            translated_texts = self._translate_batch(inputs)

            for seg, translated in zip(batch, translated_texts):
                out.append(Segment(start=seg.start, end=seg.end, text=translated.strip()))

            logger.info('Translation progress: %d/%d', min(start + batch_size, len(segments)), len(segments))

        logger.info('Translation completed. segments=%d', len(out))
        return out
