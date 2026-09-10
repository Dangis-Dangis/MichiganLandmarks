"""Split two-sided historical marker plaques into English and other-language text.

Keep the rules here in sync with the copy in app.js (EN_FUNCTION_WORDS, stubs, density).

Michigan History Center markers often put English on one face and Polish, Finnish,
French, or Anishinaabemowin on the other. The pipeline concatenates both faces;
this module keeps English as the description/summary and leaves the other
inscription available for a labeled detail section.
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[A-Za-z']+")
_EN_FUNCTION_WORDS = frozenset(
    "the of and to in a is was for that with as on by from this were are at "
    "which its his her their been had have has or an".split()
)
# Short DNR back-face stubs that repeat the front instead of a translation.
_SAME_AS_FRONT_RE = re.compile(
    r"(?is)^(?:.*\n)?same(?:\s+text)?(?:\s+as(?:\s+the)?\s+front)?\.?\s*$"
)
# Below this word count a side is a title or stub, not a foreign plaque body.
_SHORT_SIDE_WORDS = 24
_EN_MIN_HITS = 4
_EN_MIN_DENSITY = 0.08


def plaque_sides(text: str | None) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in re.split(r"\n\n+", text) if part.strip()]


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


def is_same_as_front_stub(text: str) -> bool:
    if not _SAME_AS_FRONT_RE.match((text or "").strip()):
        return False
    return len(_words(text)) < _SHORT_SIDE_WORDS


def looks_english(text: str) -> bool:
    words = _words(text)
    if len(words) < _SHORT_SIDE_WORDS:
        return True
    hits = sum(1 for w in words if w in _EN_FUNCTION_WORDS)
    return hits >= _EN_MIN_HITS and hits / len(words) >= _EN_MIN_DENSITY


def partition_plaque(text: str | None) -> tuple[str | None, str | None]:
    """Return (english, other_language) plaque text. Either side may be None."""
    sides = plaque_sides(text)
    english: list[str] = []
    other: list[str] = []
    for side in sides:
        if is_same_as_front_stub(side):
            continue
        if looks_english(side):
            english.append(side)
        else:
            other.append(side)
    en = "\n\n".join(english) or None
    ot = "\n\n".join(other) or None
    if en is None and ot is None:
        cleaned = (text or "").strip() or None
        return cleaned, None
    if en is None:
        return (text or "").strip() or None, None
    return en, ot


def english_plaque_text(text: str | None) -> str | None:
    english, _other = partition_plaque(text)
    return english


def partition_sides(sides: list[str]) -> tuple[str | None, str | None]:
    """Partition already-split front/back strings the same way as concatenated text."""
    return partition_plaque("\n\n".join(s for s in sides if s))
