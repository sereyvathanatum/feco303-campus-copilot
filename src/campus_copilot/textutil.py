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
    """A crude suffix stripper: enough to match 'fines'/'fine', 'sessions'/'session', 'classes'/'class'."""
    if len(word) <= 3:
        return word
    for suffix, keep in (("ies", "y"), ("ied", "y"), ("ings", ""), ("ing", ""), ("ed", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)] + keep
    for sibilant in ("sses", "shes", "ches", "xes", "zes"):
        if word.endswith(sibilant):
            return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
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
    """Share of the question's content terms (or Khmer trigrams) that appear in the passage.

    Terms are weighted by length, a cheap stand-in for specificity: a missing 'cafeteria'
    or 'parking' weighs more than a missing 'cost'.
    """
    weights: dict[str, int] = {}
    for word in _WORD.findall(question.lower()):
        if word not in STOP and len(word) > 1:
            weights[stem(word)] = max(weights.get(stem(word), 0), len(word))  # weight by the unstemmed word
    q_grams = khmer_grams(question)
    scores = []
    if weights:
        p_terms = set(terms(passage))
        scores.append(sum(w for t, w in weights.items() if t in p_terms) / sum(weights.values()))
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
