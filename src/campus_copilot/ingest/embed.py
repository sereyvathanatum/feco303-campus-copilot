"""Stage 5, embed: passage vectors for every chunk that has none cached for the current model.

The cache is keyed by chunk hash and model (plus input type), so re-ingesting
identical text makes zero embedding calls, and switching between the offline
hashing encoder and NIM embeds only what is missing for the new model.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..rag.embeddings import BaseEmbedder, EmbeddingError
from .store import cached_vectors, put_vectors


def embed_stage(conn: sqlite3.Connection, manifest: list[dict], chunks: list[dict], embedder: BaseEmbedder,
                batch_size: int, log_path: Path) -> dict:
    stale = {d["source_id"] for d in manifest if d["status"] in {"new", "changed", "removed"}}
    wanted: dict[str, str] = {c["chunk_hash"]: c["text"] for c in chunks if c["source_id"] not in
                              {d["source_id"] for d in manifest if d["status"] == "removed"}}
    for row in conn.execute("SELECT chunk_hash, text, source_id FROM chunks"):
        if row["source_id"] not in stale:
            wanted.setdefault(row["chunk_hash"], row["text"])
    key = embedder.cache_key("passage")
    cached = cached_vectors(conn, key, list(wanted))
    missing = [h for h in wanted if h not in cached]
    started = time.perf_counter()
    batches = 0
    calls_before, tokens_before = embedder.stats.calls, embedder.stats.tokens
    with log_path.open("a", encoding="utf-8") as log:
        for start in range(0, len(missing), batch_size):
            part = missing[start:start + batch_size]
            t0 = time.perf_counter()
            try:
                vectors = embedder.embed_documents([wanted[h] for h in part])
            except EmbeddingError as exc:
                log.write(json.dumps({"batch": batches, "n": len(part), "error": str(exc), "model": key}) + "\n")
                raise
            put_vectors(conn, key, list(zip(part, vectors)))
            batches += 1
            log.write(json.dumps({"batch": batches, "n": len(part), "ms": round((time.perf_counter() - t0) * 1000, 1),
                                  "model": key, "dim": len(vectors[0]) if vectors else 0}) + "\n")
        log.write(json.dumps({"summary": True, "cache_hits": len(cached), "embedded": len(missing),
                              "model": key}) + "\n")
    return {
        "model": embedder.model, "cache_key": key, "offline_encoder": embedder.offline,
        "input_type_sent": key.split("|")[-1], "chunks_considered": len(wanted), "cache_hits": len(cached),
        "embedded": len(missing), "batches": batches, "calls": embedder.stats.calls - calls_before,
        "tokens": embedder.stats.tokens - tokens_before, "ms": round((time.perf_counter() - started) * 1000, 1),
    }
