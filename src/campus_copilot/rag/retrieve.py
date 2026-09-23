"""Retrieval modes (docs/implementation-plan.md §8.4.4), each on any store backend.

* `lexical`: FTS5 `bm25()` (hashing-encoder fallback when FTS5 is missing)
* `dense`: cosine over the stored embeddings
* `hybrid`: reciprocal-rank fusion of lexical and dense
* `dense+rerank`: the NIM reranker over the dense candidates
* `dense+judge`: the decision model's passage questions over the dense candidates

Every result is labelled with its score type, store, and latency.
"""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass, field

from ..ingest import store as kb
from .embeddings import HashingEmbedder

MODES = ("lexical", "dense", "hybrid", "dense+rerank", "dense+judge")
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
                "citation": self.citation}


@dataclass
class RetrievalResult:
    query: str
    mode: str
    store: str
    chunks: list[ScoredChunk]
    latency_ms: float
    notes: list[str] = field(default_factory=list)
    dropped: list[ScoredChunk] = field(default_factory=list)


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
        return [_scored(by_id[r["chunk_id"]], -r["s"], "bm25 (higher is better)", "fts5")
                for r in rows if r["chunk_id"] in by_id], "fts5 bm25"
    encoder = HashingEmbedder()
    from .stores.sqlite_numpy import SqliteNumpyStore

    store = SqliteNumpyStore(conn, encoder)
    return [_scored(row, s, "hashing cosine (FTS5 missing)", "hashing") for row, s in store.search(query, k)], \
        "hashing fallback"


def _rows(conn: sqlite3.Connection, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    return {r["chunk_id"]: dict(r) for r in conn.execute(
        f"SELECT chunk_id, source_id, page, section, text, token_count, language FROM chunks WHERE chunk_id IN ({marks})",
        ids)}


def dense(store, query: str, k: int) -> list[ScoredChunk]:
    return [_scored(row, s, "cosine", store.name) for row, s in store.search(query, k)]


def rrf(*rankings: list[ScoredChunk], k: int) -> list[ScoredChunk]:
    scores: dict[str, float] = {}
    first: dict[str, ScoredChunk] = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking, start=1):
            scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            first.setdefault(chunk.chunk_id, chunk)
    fused = sorted(scores, key=lambda cid: -scores[cid])[:k]
    out = []
    for cid in fused:
        c = first[cid]
        out.append(ScoredChunk(c.chunk_id, c.source_id, c.page, c.section, c.text, c.token_count, c.language,
                               round(scores[cid], 5), "reciprocal-rank fusion", f"fts5+{c.store}"))
    return out


def rerank(settings, query: str, candidates: list[ScoredChunk], k: int, session=None) -> tuple[list[ScoredChunk], str]:
    import requests

    if not settings.has_nim:
        return candidates[:k], "reranker skipped (no NIM key or offline mode); dense order kept"
    model = settings.rerank_model
    url = f"https://ai.api.nvidia.com/v1/retrieval/{model}/reranking"
    body = {"model": model, "query": {"text": query}, "passages": [{"text": c.text} for c in candidates]}
    try:
        http = session or requests
        response = http.post(url, json=body, timeout=30,
                             headers={"Authorization": f"Bearer {settings.nemotron_api_key}", "Accept": "application/json"})
    except requests.RequestException as exc:
        return candidates[:k], f"reranker unavailable ({type(exc).__name__}); dense order kept"
    if response.status_code != 200:
        return candidates[:k], f"reranker unavailable (HTTP {response.status_code}); dense order kept"
    ranked = sorted(response.json().get("rankings", []), key=lambda r: -r["logit"])[:k]
    out = []
    for r in ranked:
        c = candidates[r["index"]]
        out.append(ScoredChunk(c.chunk_id, c.source_id, c.page, c.section, c.text, c.token_count, c.language,
                               round(float(r["logit"]), 4), "reranker logit", c.store))
    return out, f"reranked by {model}"


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


def retrieve(query: str, settings, conn: sqlite3.Connection | None = None, embedder=None, mode: str | None = None,
             store: str | None = None, k: int | None = None, decider=None, session=None) -> RetrievalResult:
    from .embeddings import get_embedder
    from .stores.base import get_store

    started = time.perf_counter()
    mode = mode or settings.profile.get("rag.mode", "hybrid")
    if mode not in MODES:
        raise ValueError(f"unknown retrieval mode {mode!r}; modes: {', '.join(MODES)}")
    k = int(k or settings.profile.get("rag.top_k", 4))
    own_conn = conn is None
    conn = conn or kb.connect()
    embedder = embedder or get_embedder(settings)
    store_name = store or settings.profile.get("rag.store", "sqlite")
    notes: list[str] = []
    dropped: list[ScoredChunk] = []
    try:
        if mode == "lexical":
            chunks, how = lexical(conn, query, k)
            notes.append(how)
            store_name = "fts5"
        else:
            vector_store = get_store(store_name, embedder, conn)
            if mode == "dense":
                chunks = dense(vector_store, query, k)
            elif mode == "hybrid":
                lex, how = lexical(conn, query, k * 3)
                chunks = rrf(lex, dense(vector_store, query, k * 3), k=k)
                notes.append(how)
            elif mode == "dense+rerank":
                chunks, note = rerank(settings, query, dense(vector_store, query, k * 3), k, session=session)
                notes.append(note)
            else:
                chunks, dropped, note = judge(settings, query, dense(vector_store, query, k * 2), k, decider)
                notes.append(note)
        for rank, c in enumerate(chunks, start=1):
            c.rank = rank
        if embedder.offline and mode != "lexical":
            notes.append("dense vectors come from the offline hashing encoder")
        return RetrievalResult(query, mode, store_name, chunks, round((time.perf_counter() - started) * 1000, 1),
                               notes, dropped)
    finally:
        if own_conn:
            conn.close()
