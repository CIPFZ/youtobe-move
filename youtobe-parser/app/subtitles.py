from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Segment:
    start: float
    end: float
    text: str


def make_bilingual_segments(original: list[Segment], translated: list[Segment]) -> list[Segment]:
    """Build bilingual subtitles: translated (Chinese) first, source (English) second."""
    if len(original) != len(translated):
        raise ValueError('original and translated segments length mismatch')

    out: list[Segment] = []
    for src, tgt in zip(original, translated):
        zh = (tgt.text or '').strip()
        en = (src.text or '').strip()
        if zh and en and zh != en:
            # Chinese on top, English on bottom with smaller gray inline style.
            text = f"{zh}\\N{{\\fs34\\c&H00C8C8C8&}}{en}{{\\r}}"
        else:
            text = zh or en
        out.append(Segment(start=src.start, end=src.end, text=text))
    return out


def sec_to_srt(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def sec_to_ass(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int((t - int(t)) * 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def write_srt(segments: list[Segment], path: Path) -> None:
    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        lines.extend([str(i), f'{sec_to_srt(seg.start)} --> {sec_to_srt(seg.end)}', seg.text.strip(), ''])
    path.write_text('\n'.join(lines), encoding='utf-8')


def write_ass(segments: list[Segment], path: Path) -> None:
    header = """[Script Info]
ScriptType: v4.00+
Collisions: Normal
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Arial,54,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,2.8,0,2,36,36,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    body = []
    for seg in segments:
        text = seg.text.replace('\n', r'\N')
        body.append(f'Dialogue: 0,{sec_to_ass(seg.start)},{sec_to_ass(seg.end)},Default,,0,0,0,,{text}')
    path.write_text(header + '\n'.join(body) + '\n', encoding='utf-8')
