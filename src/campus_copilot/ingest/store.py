"""Knowledge-base tables (`runs/kb.db`) and stage 6, store.

Tables: `documents`, `chunks`, `embedding_cache`, `ingest_runs`, and the FTS5 index
`chunks_fts`. Vector backends (`rag/stores/`) read chunks and cached vectors from
here, so every backend is filled from the same chunks and embeddings.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import numpy as np

from .. import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    source_id TEXT PRIMARY KEY, file TEXT, sha256 TEXT, format TEXT, title TEXT, language TEXT,
    licence TEXT, origin TEXT, pages INTEGER, status TEXT, ingested_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, page INTEGER, section TEXT, text TEXT NOT NULL,
    token_count INTEGER NOT NULL, position INTEGER NOT NULL, language TEXT, chunk_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE TABLE IF NOT EXISTS embedding_cache (
    chunk_hash TEXT NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL, vector BLOB NOT NULL,
    PRIMARY KEY (chunk_hash, model)
);
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id TEXT PRIMARY KEY, started TEXT, finished TEXT, stats TEXT
);
"""


def fts5_available() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        conn.close()


def kb_path() -> Path:
    return config.runs_dir() / "kb.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or kb_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if fts5_available():
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5("
                     "text, chunk_id UNINDEXED, source_id UNINDEXED, tokenize='porter unicode61 remove_diacritics 2')")
    return conn


def documents(conn: sqlite3.Connection) -> dict[str, dict]:
    return {r["source_id"]: dict(r) for r in conn.execute("SELECT * FROM documents")}


# ------------------------------------------------------------------ embeddings

def to_blob(vector) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cached_vectors(conn: sqlite3.Connection, model: str, hashes: list[str]) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for start in range(0, len(hashes), 500):
        part = hashes[start:start + 500]
        marks = ",".join("?" for _ in part)
        for row in conn.execute(f"SELECT chunk_hash, vector FROM embedding_cache WHERE model = ? AND chunk_hash IN ({marks})",
                                (model, *part)):
            found[row["chunk_hash"]] = row["vector"]
    return found


def put_vectors(conn: sqlite3.Connection, model: str, items: list[tuple[str, list[float]]]) -> None:
    conn.executemany("INSERT OR REPLACE INTO embedding_cache (chunk_hash, model, dim, vector) VALUES (?, ?, ?, ?)",
                     [(h, model, len(v), to_blob(v)) for h, v in items])
    conn.commit()


# ---------------------------------------------------------------- store stage

def store_stage(conn: sqlite3.Connection, manifest: list[dict], chunks: list[dict], backends: list[str],
                embedder) -> dict:
    """Upsert documents and chunks, delete chunks of changed or removed documents, sync every backend."""
    from ..rag.stores import base as stores

    started = time.perf_counter()
    processed = {d["source_id"] for d in manifest if d["status"] in {"new", "changed"}}
    removed = {d["source_id"] for d in manifest if d["status"] == "removed"}
    stale = processed | removed
    deleted = 0
    for source_id in stale:
        deleted += conn.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,)).rowcount
        if fts5_available():
            conn.execute("DELETE FROM chunks_fts WHERE source_id = ?", (source_id,))
    for source_id in removed:
        conn.execute("UPDATE documents SET status = CASE WHEN status = 'excluded' THEN 'excluded' ELSE 'removed' END "
                     "WHERE source_id = ?", (source_id,))
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for doc in manifest:
        if doc["source_id"] in processed:
            conn.execute(
                """INSERT OR REPLACE INTO documents (source_id, file, sha256, format, title, language, licence, origin,
                   pages, status, ingested_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ingested', ?)""",
                (doc["source_id"], doc["file"], doc["sha256"], doc["format"], doc["title"], doc["language"],
                 doc["licence"], doc["origin"], doc.get("pages"), now))
    rows = [(c["chunk_id"], c["source_id"], c.get("page"), c.get("section"), c["text"], c["token_count"],
             c["position"], c.get("language"), c["chunk_hash"]) for c in chunks if c["source_id"] in processed]
    conn.executemany("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    if fts5_available():
        conn.executemany("INSERT INTO chunks_fts (text, chunk_id, source_id) VALUES (?, ?, ?)",
                         [(r[4], r[0], r[1]) for r in rows])
    conn.commit()
    backend_stats = {}
    for name in backends:
        store = stores.get_store(name, embedder=embedder, conn=conn)
        backend_stats[name] = store.sync(removed_sources=sorted(stale))
    total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    return {
        "inserted_chunks": len(rows), "deleted_chunks": deleted, "documents_processed": sorted(processed),
        "documents_removed": sorted(removed), "total_chunks": total, "backends": backend_stats,
        "fts5": fts5_available(), "index_ms": round((time.perf_counter() - started) * 1000, 1),
        "kb_bytes": Path(conn.execute("PRAGMA database_list").fetchone()[2]).stat().st_size,
    }


def record_run(conn: sqlite3.Connection, run_id: str, started: str, finished: str, stats: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO ingest_runs VALUES (?, ?, ?, ?)",
                 (run_id, started, finished, json.dumps(stats, ensure_ascii=False, default=str)))
    conn.commit()
