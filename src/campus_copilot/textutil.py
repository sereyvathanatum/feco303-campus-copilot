"""Small text helpers shared by the offline stubs (stub model, stub decider)."""

from __future__ import annotations

import re

STOP = set(("a an the of to in on for and or is are be by with at from as it this that what which how when where who "
            "whom does do did can could should would will after before per there any some about into than then them "
            "they its their was were been being has have had not no please tell show give much many happens "
            "happen get also just".split()))
_WORD = re.compile(r"[a-z0-9]+")
_KHMER = re.compile(r"[ក-៿]+")
_SENTENCE = re.compile(r"(?<=[.!?។])\s+|\n+")


def stem(word: str) -> str:
    for suffix in ("ings", "ing", "ies", "ied", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            return base + "y" if suffix in {"ies", "ied"} else base
    return word


def terms(text: str) -> list[str]:
    words = [stem(w) for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1]
    return list(dict.fromkeys(words))


def khmer_grams(text: str) -> set[str]:
    grams: set[str] = set()
    for run in _KHMER.findall(text):
        grams.update(run[i:i + 3] for i in range(max(1, len(run) - 2)))
    return grams


def coverage(question: str, passage: str) -> float:
    """Share of the question's content terms (or Khmer trigrams) that appear in the passage."""
    q_terms = terms(question)
    q_grams = khmer_grams(question)
    scores = []
    if q_terms:
        p_terms = set(terms(passage))
        scores.append(sum(1 for t in q_terms if t in p_terms) / len(q_terms))
    if q_grams:
        p_grams = khmer_grams(passage)
        scores.append(len(q_grams & p_grams) / len(q_grams))
    return max(scores) if scores else 0.0


def sentences(text: str) -> list[str]:
    # Hard line wraps inside a paragraph (PDF text) are joined first; blank lines and list items still split.
    text = re.sub(r"(?<![\n.!?:។])\n(?![\n\-•])", " ", text)
    parts = [p.strip(" -•") for p in _SENTENCE.split(text)]
    return [p for p in parts if len(p) > 3]


def has_khmer(text: str) -> bool:
    return bool(_KHMER.search(text))
