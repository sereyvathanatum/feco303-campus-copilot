"""Second-stage reranking (`rag.reranker`): score a candidate pool against the query, keep the best `rag.top_k`.

First-stage retrieval (lexical, dense, hybrid) is built for recall and speed: the query vector and the
chunk vectors are computed apart, so a chunk that only mentions "tuition" can outrank the table row
that answers "yearly tuition for Cyber Security". A reranker reads the query and each passage together
and scores the pair. Backends:

* `nim`: the NVIDIA cross-encoder reranker (`NIM_RERANK_MODEL`); one request for the whole pool;
  score = logit, relevance = sigmoid(logit)
* `jev`: the decision model's passage questions (one request per passage, in parallel);
  relevance = 0.6 x has_answer + 0.4 x relevant; the verdicts stay on the chunks, so the passage
  filter does not ask again
* `local`: offline heuristic, no model: weighted query-term coverage, query-bigram overlap, and the
  first-stage rank. Labelled as a heuristic; it is not a cross-encoder
* `auto`: `nim` when a NIM key is available, else `local`; a failed `nim` call falls back to `local`

The result is ordered by relevance, best first. That order is the order of passages in the prompt,
and each passage carries its rank and relevance there (see `rag/answer.py`).
"""

from __future__ import annotations

import logging
import math
import re
import time
from dataclasses import dataclass, field

from ..textutil import STOP, coverage, stem

log = logging.getLogger(__name__)
RERANKERS = ("auto", "nim", "jev", "local")
_WORD = re.compile(r"[a-z0-9]+")


class RerankError(RuntimeError):
    pass


@dataclass
class RerankOutcome:
    chunks: list  # list[ScoredChunk], best first, at most k
    backend: str
    ms: float
    notes: list[str] = field(default_factory=list)
    below_threshold: list = field(default_factory=list)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, x))))


def nim_scores(settings, query: str, texts: list[str], session=None) -> list[float]:
    import requests

    if not settings.has_nim:
        raise RerankError("no NIM key or offline mode")
    model = settings.rerank_model
    url = f"https://ai.api.nvidia.com/v1/retrieval/{model}/reranking"
    body = {"model": model, "query": {"text": query}, "passages": [{"text": t} for t in texts], "truncate": "END"}
    try:
        response = (session or requests).post(
            url, json=body, timeout=30,
            headers={"Authorization": f"Bearer {settings.nemotron_api_key}", "Accept": "application/json"})
    except requests.RequestException as exc:
        raise RerankError(type(exc).__name__) from exc
    if response.status_code != 200:
        raise RerankError(f"HTTP {response.status_code}")
    scores = [float("-inf")] * len(texts)
    for item in response.json().get("rankings", []):
        scores[int(item["index"])] = float(item["logit"])
    return scores


def jev_scores(decider, query: str, candidates: list) -> list[float]:
    verdicts = decider.judge_passages(query, [c.text for c in candidates])
    scores = []
    for chunk, verdict in zip(candidates, verdicts):
        chunk.judge = verdict
        scores.append(0.6 * float(verdict.get("has_answer", 0.0)) + 0.4 * float(verdict.get("relevant", 0.0)))
    return scores


def _stems(text: str) -> list[str]:
    return [stem(w) for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1]


def local_scores(query: str, candidates: list) -> list[float]:
    q = _stems(query)
    q_pairs = set(zip(q, q[1:]))
    n = max(1, len(candidates))
    scores = []
    for index, chunk in enumerate(candidates):
        words = _stems(chunk.text)
        pairs = len(q_pairs & set(zip(words, words[1:]))) / len(q_pairs) if q_pairs else 0.0
        prior = 1.0 - index / n  # candidates arrive in first-stage order
        scores.append(0.6 * coverage(query, chunk.text) + 0.15 * pairs + 0.25 * prior)
    return scores


def resolve(settings) -> str:
    backend = str(settings.profile.get("rag.reranker", "auto"))
    if backend not in RERANKERS:
        raise ValueError(f"rag.reranker must be one of {', '.join(RERANKERS)}, not {backend!r}")
    if backend == "auto":
        return "nim" if settings.has_nim else "local"
    return backend


def rerank(settings, query: str, candidates: list, k: int, decider=None, session=None,
           backend: str | None = None) -> RerankOutcome:
    backend = backend or resolve(settings)
    started = time.perf_counter()
    notes: list[str] = []
    if not candidates:
        return RerankOutcome([], backend, 0.0, notes)
    try:
        if backend == "nim":
            scores = nim_scores(settings, query, [c.text for c in candidates], session=session)
            relevance = [_sigmoid(s) for s in scores]
            label = f"reranker logit ({settings.rerank_model})"
        elif backend == "jev":
            from ..decisions.base import get_decider

            scores = jev_scores(decider or get_decider(settings), query, candidates)
            relevance = scores
            label = "decision-model relevance (0.6 has_answer + 0.4 relevant)"
        else:
            scores = local_scores(query, candidates)
            relevance = scores
            label = "local rerank heuristic (coverage, bigrams, first-stage rank)"
    except RerankError as exc:
        notes.append(f"{backend} reranker unavailable ({exc}); local heuristic reranker used")
        log.warning("reranker %s unavailable (%s); falling back to the local heuristic", backend, exc)
        backend = "local"
        scores = local_scores(query, candidates)
        relevance = scores
        label = "local rerank heuristic (coverage, bigrams, first-stage rank)"
    floor = float(settings.profile.get("rag.rerank_min_relevance", 0.0) or 0.0)
    kept, below = [], []
    for index in sorted(range(len(candidates)), key=lambda i: -scores[i]):
        chunk = candidates[index]
        chunk.signals.update(first_stage_rank=index + 1, rerank=round(scores[index], 4),
                             relevance=round(relevance[index], 4), reranker=backend)
        chunk.score, chunk.score_type = round(scores[index], 4), label
        (kept if relevance[index] >= floor else below).append(chunk)
    ms = round((time.perf_counter() - started) * 1000, 1)
    notes.insert(0, f"reranked {len(candidates)} candidates by {backend} in {ms:.0f} ms; kept top {min(k, len(kept))}")
    if below:
        notes.append(f"{len(below)} candidates below rag.rerank_min_relevance {floor}")
    return RerankOutcome(kept[:k], backend, ms, notes, below)
