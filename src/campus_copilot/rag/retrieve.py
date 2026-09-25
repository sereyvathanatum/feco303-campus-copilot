"""Retrieval modes (docs/implementation-plan.md §8.4.4), each on any store backend.

* `lexical`: FTS5 `bm25()` (hashing-encoder fallback when FTS5 is missing)
* `dense`: cosine over the stored embeddings
* `hybrid`: reciprocal-rank fusion of lexical and dense
* `dense+rerank`, `hybrid+rerank`: a candidate pool of `rag.candidates` from the first stage, then the
  reranker (`rag.reranker`, see `rerank.py`) keeps the best `rag.top_k`, ordered by relevance
* `dense+judge`: the decision model's passage questions over the dense candidates

Every result is labelled with its score type, store, and latency. Each chunk also carries `signals`:
its lexical and dense ranks and scores, the fused score, and the reranker score, so a log or the
`--show-chunks` view can show why a chunk made the context.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field

from ..ingest import store as kb
from .embeddings import HashingEmbedder

log = logging.getLogger(__name__)
MODES = ("lexical", "dense", "hybrid", "dense+rerank", "hybrid+rerank", "dense+judge")
LONG_CONTEXT = "long_context"  # E15: every handbook chunk goes into the prompt, no retrieval at all
_TERM = re.compile(r"[A-Za-z0-9]+|[ក-៿]+")
_STOP = set(("a an the of to in on for and or is are be by with at from as it this that what which how when where "
             "who whom does do did can could should would will after before per there any some about into than "
             "then them they its their was were been being has have had not no".split()))
RRF_K = 60


@dataclass
class ScoredChunk:
    chunk_id: str
    source_id: str
    page: int | None
    section: str | None
    text: str
    token_count: int
    language: str | None
    score: float
    score_type: str
    store: str
    rank: int = 0
    judge: dict | None = None
    signals: dict = field(default_factory=dict)

    @property
    def locator(self) -> str:
        return f"p.{self.page}" if self.page else f"§ {self.section}"

    @property
    def citation(self) -> str:
        return f"[{self.source_id} p.{self.page}]" if self.page else f"[{self.source_id} § {self.section}]"

    def as_dict(self) -> dict:
        return {"chunk_id": self.chunk_id, "source_id": self.source_id, "page": self.page, "section": self.section,
                "text": self.text, "token_count": self.token_count, "language": self.language, "score": self.score,
                "score_type": self.score_type, "store": self.store, "rank": self.rank, "judge": self.judge,
                "signals": dict(self.signals), "citation": self.citation}

    def describe(self) -> str:
        """One line for logs: rank, citation, and every signal that placed the chunk."""
        s = self.signals
        parts = [f"#{self.rank}" if self.rank else "-", self.citation, f"{self.score_type} {self.score:.4f}"]
        if "relevance" in s:
            parts.append(f"relevance {s['relevance']:.3f}")
        if "lexical_rank" in s:
            parts.append(f"lexical #{s['lexical_rank']} (bm25 {s['bm25']:.2f})")
        if "dense_rank" in s:
            parts.append(f"dense #{s['dense_rank']} (cos {s['cosine']:.3f})")
        if "rrf" in s:
            parts.append(f"rrf {s['rrf']:.4f}")
        if "first_stage_rank" in s:
            parts.append(f"first-stage #{s['first_stage_rank']}")
        parts.append(f"{self.token_count} tok")
        return "  ".join(parts)


@dataclass
class RetrievalResult:
    query: str
    mode: str
    store: str
    chunks: list[ScoredChunk]
    latency_ms: float
    notes: list[str] = field(default_factory=list)
    dropped: list[ScoredChunk] = field(default_factory=list)
    candidates: int = 0


def _scored(row: dict, score: float, score_type: str, store: str) -> ScoredChunk:
    return ScoredChunk(row["chunk_id"], row["source_id"], row.get("page"), row.get("section"), row["text"],
                       int(row.get("token_count") or 0), row.get("language"), round(float(score), 5), score_type, store)


def fts_query(text: str) -> str:
    terms = [t for t in _TERM.findall(text.lower()) if t not in _STOP and len(t) > 1]
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(terms))


def lexical(conn: sqlite3.Connection, query: str, k: int) -> tuple[list[ScoredChunk], str]:
    if kb.fts5_available():
        match = fts_query(query)
        if not match:
            return [], "fts5 bm25"
        rows = conn.execute(
            "SELECT f.chunk_id, bm25(chunks_fts) AS s FROM chunks_fts f WHERE chunks_fts MATCH ? ORDER BY s LIMIT ?",
            (match, k)).fetchall()
        ids = [r["chunk_id"] for r in rows]
        by_id = _rows(conn, ids)
        out = [_scored(by_id[r["chunk_id"]], -r["s"], "bm25 (higher is better)", "fts5")
               for r in rows if r["chunk_id"] in by_id]
        for rank, c in enumerate(out, start=1):
            c.signals.update(lexical_rank=rank, bm25=c.score)
        return out, "fts5 bm25"
    encoder = HashingEmbedder()
    from .stores.sqlite_numpy import SqliteNumpyStore

    store = SqliteNumpyStore(conn, encoder)
    out = [_scored(row, s, "hashing cosine (FTS5 missing)", "hashing") for row, s in store.search(query, k)]
    for rank, c in enumerate(out, start=1):
        c.signals.update(lexical_rank=rank, bm25=c.score)
    return out, "hashing fallback"


def _rows(conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    return {r["chunk_id"]: dict(r) for r in conn.execute(
        f"SELECT chunk_id, source_id, page, section, text, token_count, language FROM chunks WHERE chunk_id IN ({marks})",
        ids)}


def dense(store, query: str, k: int) -> list[ScoredChunk]:
    out = [_scored(row, s, "cosine", store.name) for row, s in store.search(query, k)]
    for rank, c in enumerate(out, start=1):
        c.signals.update(dense_rank=rank, cosine=c.score)
    return out


def rrf(*rankings: list[ScoredChunk], k: int) -> list[ScoredChunk]:
    scores: dict[str, float] = {}
    first: dict[str, ScoredChunk] = {}
    signals: dict[str, dict] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            first.setdefault(chunk.chunk_id, chunk)
            signals.setdefault(chunk.chunk_id, {}).update(chunk.signals)
    fused = sorted(scores, key=lambda cid: -scores[cid])[:k]
    out = []
    for cid in fused:
        c = first[cid]
        out.append(ScoredChunk(c.chunk_id, c.source_id, c.page, c.section, c.text, c.token_count, c.language,
                               round(scores[cid], 5), "reciprocal-rank fusion", f"fts5+{c.store}",
                               signals={**signals[cid], "rrf": round(scores[cid], 5)}))
    return out


def judge(settings, query: str, candidates: list[ScoredChunk], k: int, decider=None) -> tuple[list[ScoredChunk], list[ScoredChunk], str]:
    """Keep passages the decision model judges relevant; drop injected or irrelevant ones."""
    from ..decisions.base import get_decider

    decider = decider or get_decider(settings)
    verdicts = decider.judge_passages(query, [c.text for c in candidates])
    policy = settings.profile
    keep, dropped = [], []
    for chunk, verdict in zip(candidates, verdicts):
        chunk.judge = verdict
        if verdict.get("injection", 0.0) > float(policy.get("policy.passage_injection", 0.70)):
            dropped.append(chunk)
        elif verdict.get("relevant", 0.0) < float(policy.get("policy.passage_relevant", 0.45)):
            dropped.append(chunk)
        else:
            keep.append(chunk)
    keep.sort(key=lambda c: -(c.judge or {}).get("has_answer", 0.0))
    for c in keep:
        c.score, c.score_type = round((c.judge or {}).get("has_answer", 0.0), 4), "judge has_answer"
    return keep[:k], dropped, f"judged by {decider.name}"


def _long_context(query: str, settings, conn, started: float) -> RetrievalResult:
    own = conn is None
    conn = conn or kb.connect()
    try:
        source = settings.profile.get("rag.long_context_source", "academic-info")
        rows = conn.execute("SELECT chunk_id, source_id, page, section, text, token_count, language FROM chunks "
                            "WHERE source_id = ? ORDER BY page, position", (source,)).fetchall()
        chunks = [_scored(dict(r), 1.0, "whole document in context", "none") for r in rows]
        for rank, c in enumerate(chunks, start=1):
            c.rank = rank
        tokens = sum(c.token_count for c in chunks)
        return RetrievalResult(query, LONG_CONTEXT, "none", chunks, round((time.perf_counter() - started) * 1000, 1),
                               [f"long context: all {len(chunks)} chunks of {source} ({tokens} tokens) in the prompt"])
    finally:
        if own:
            conn.close()


def _first_stage(base: str, conn, vector_store, query: str, n: int, notes: list[str]) -> list[ScoredChunk]:
    if base == "lexical":
        chunks, how = lexical(conn, query, n)
        notes.append(how)
        return chunks
    if base == "dense":
        return dense(vector_store, query, n)
    lex, how = lexical(conn, query, n * 3 if n <= 10 else n)
    notes.append(how)
    return rrf(lex, dense(vector_store, query, n * 3 if n <= 10 else n), k=n)


def retrieve(query: str, settings, conn: sqlite3.Connection | None = None, embedder=None, mode: str | None = None,
             store: str | None = None, k: int | None = None, decider=None, session=None) -> RetrievalResult:
    from .embeddings import get_embedder
    from .rerank import rerank
    from .stores.base import get_store

    started = time.perf_counter()
    mode = mode or settings.profile.get("rag.mode", "hybrid")
    if mode == LONG_CONTEXT:
        return _long_context(query, settings, conn, started)
    if mode not in MODES:
        raise ValueError(f"unknown retrieval mode {mode!r}; modes: {', '.join(MODES)}")
    k = int(k or settings.profile.get("rag.top_k", 4))
    pool = max(k, int(settings.profile.get("rag.candidates", 20)))
    base, _, second = mode.partition("+")
    own_conn = conn is None
    conn = conn or kb.connect()
    embedder = embedder or get_embedder(settings)
    store_name = store or settings.profile.get("rag.store", "sqlite")
    notes: list[str] = []
    dropped: list[ScoredChunk] = []
    try:
        vector_store = None if base == "lexical" else get_store(store_name, embedder, conn)
        if base == "lexical":
            store_name = "fts5"
        size = pool if second == "rerank" else (k * 2 if second == "judge" else k)
        candidates = _first_stage(base, conn, vector_store, query, size, notes)
        if not settings.profile.get("data.include_adversarial", False):
            # the poisoned E13 document may sit in the knowledge base; only E13 profiles retrieve it
            candidates = [c for c in candidates if not c.source_id.startswith("adversarial-")]
        log.info("retrieve %s @ %s: %d candidates for %r", mode, store_name, len(candidates), query)
        for rank, c in enumerate(candidates, start=1):
            log.debug("  candidate %2d  %s", rank, c.describe())
        if second == "rerank":
            outcome = rerank(settings, query, candidates, k, decider=decider, session=session)
            chunks, notes = outcome.chunks, notes + outcome.notes
            dropped = outcome.below_threshold
        elif second == "judge":
            chunks, dropped, note = judge(settings, query, candidates, k, decider)
            notes.append(note)
        else:
            chunks = candidates[:k]
        for rank, c in enumerate(chunks, start=1):
            c.rank = rank
        if embedder.offline and base != "lexical":
            notes.append("dense vectors come from the offline hashing encoder")
        latency = round((time.perf_counter() - started) * 1000, 1)
        log.info("retrieve kept %d of %d in %.0f ms%s", len(chunks), len(candidates), latency,
                 f" ({'; '.join(notes)})" if notes else "")
        for c in chunks:
            log.info("  context %s", c.describe())
        return RetrievalResult(query, mode, store_name, chunks, latency, notes, dropped, len(candidates))
    finally:
        if own_conn:
            conn.close()
