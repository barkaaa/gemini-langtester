"""
Japanese text difficulty analyzer.

Primary signal: average sentence length (longer sentences → harder to parse).
Secondary signal: N1/N2 grammar surface forms (reliable hard floor).
Tertiary signal: unique kanji count per character (vocabulary richness).

Outputs L1–L10 with JLPT band (L↔JLPT: L1-2≈N5, L3-4≈N4, L5-6≈N3, L7-8≈N2, L9-10≈N1).
"""

import re
from .schemas import AnalyzeRequest, AnalyzeResponse

# N1-level grammar surface forms
_N1_PATTERNS = [
    "にもかかわらず", "に際して", "をめぐって", "にわたって", "を踏まえて",
    "いかんにかかわらず", "にほかならない", "をもって", "ならびに",
    "に至っては", "とはいえ", "のみならず", "をよそに", "のいかんによらず",
    "をものともせず", "にほかならず",
]

# N2-level grammar surface forms
_N2_PATTERNS = [
    "において", "に伴って", "に基づいて", "に応じて", "によれば",
    "ものの", "に過ぎない", "に関して", "によって", "をはじめ",
    "に比べて", "に当たって", "を通じて", "に先立って", "からすると",
    "に相違ない", "に関する",
]

_KANJI_RE  = re.compile(r"[一-鿿㐀-䶿]")
_JP_RE     = re.compile(r"[ぁ-ヿ一-鿿]")
_SENT_SPLIT = re.compile(r"[。！？!?]")


def _avg_sentence_len(text: str) -> float:
    sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    if not sents:
        return float(len(text))
    return sum(len(s) for s in sents) / len(sents)


def _unique_kanji_rate(text: str) -> float:
    """Unique kanji count per 100 characters (vocabulary diversity proxy)."""
    total = max(len(text), 1)
    unique = len(set(_KANJI_RE.findall(text)))
    return unique / total * 100


def _grammar_floor(text: str) -> int:
    """Minimum level implied by grammar patterns."""
    n1_hits = sum(1 for p in _N1_PATTERNS if p in text)
    n2_hits = sum(1 for p in _N2_PATTERNS if p in text)
    if n1_hits >= 2:
        return 9
    if n1_hits == 1:
        return 8
    if n2_hits >= 3:
        return 7
    if n2_hits >= 1:
        return 6
    return 0  # no floor


def _level_from_sent_len(avg_len: float) -> int:
    # Calibrated for JLPT passages (150-250 chars).
    # N5: short simple sentences; N1: very long complex clause stacking.
    if avg_len < 10:
        return 1
    if avg_len < 15:
        return 2
    if avg_len < 20:
        return 3
    if avg_len < 27:
        return 4
    if avg_len < 36:
        return 5
    if avg_len < 46:
        return 6
    if avg_len < 56:
        return 7
    if avg_len < 68:
        return 8
    return 9


def _level_to_band(level: int) -> str:
    if level <= 2:
        return "N5"
    if level <= 4:
        return "N4"
    if level <= 6:
        return "N3"
    if level <= 8:
        return "N2"
    return "N1"


class Pipeline:
    def analyze(self, req: AnalyzeRequest) -> AnalyzeResponse:
        text = req.text

        avg_len  = _avg_sentence_len(text)
        uk_rate  = _unique_kanji_rate(text)
        g_floor  = _grammar_floor(text)

        # Base from sentence complexity
        base = _level_from_sent_len(avg_len)

        # Vocabulary richness nudge (+1 if very high, -1 if very low)
        if uk_rate > 18:
            base = min(base + 1, 10)
        elif uk_rate < 4 and base > 1:
            base = max(base - 1, 1)

        # Grammar hard floor (only raises, never lowers)
        level = max(base, g_floor)
        level = max(1, min(10, level))

        band = _level_to_band(level)

        jp_chars = len(_JP_RE.findall(text))
        if jp_chars < 50:
            confidence = "low"
        elif jp_chars < 130:
            confidence = "medium"
        else:
            confidence = "high"

        return AnalyzeResponse(level=level, band=band, confidence=confidence)
