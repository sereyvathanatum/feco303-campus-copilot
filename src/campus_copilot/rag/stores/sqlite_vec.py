"""`sqlite-vec` store: the same rows plus a `vec0` virtual table, queried with SQL KNN.

A small local class modelled on LangChain's community `SQLiteVec` store, so the pack
does not pull in all of `langchain-community`. Current `sqlite-vec` releases search
`vec0` by exact brute force.
"""

from __future__ import annotations

import sqlite3

import numpy as np

from .base import KBVectorStore


def _load_extension(conn: sqlite3.Connection) -> None:
    import sqlite_vec

    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


def availability() -> tuple[bool, str]:
    try:
        conn = sqlite3.connect(":memory:")
        _load_extension(conn)
        version = conn.execute("select vec_version()").fetchone()[0]
        conn.close()
        return True, f"sqlite-vec {version} (vec0, exact KNN)"
    except (ImportError, AttributeError, sqlite3.OperationalError) as exc:
        return False, (f"sqlite-vec unavailable ({type(exc).__name__}); this Python build blocks SQLite extension "
                       "loading. A Python from python.org or Homebrew loads it.")


class SqliteVecStore(KBVectorStore):
    name = "sqlite_vec"
    search_kind = "vec0 KNN (exact)"

    def __init__(self, conn, embedder) -> None:
        super().__init__(conn, embedder)
        _load_extension(conn)
        conn.execute("CREATE TABLE IF NOT EXISTS vec_meta (key TEXT PRIMARY KEY, value TEXT)")

    def _meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM vec_meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def sync(self, removed_sources: list[str] | None = None) -> dict:
        rows = self.conn.execute(
            "SELECT c.rowid AS rid, e.vector, e.dim FROM chunks c "
            "JOIN embedding_cache e ON e.chunk_hash = c.chunk_hash AND e.model = ?", (self.model_key,)).fetchall()
        self.conn.execute("DROP TABLE IF EXISTS vec_chunks")
        if rows:
            dim = int(rows[0]["dim"])
            self.conn.execute(f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{dim}] distance_metric=cosine)")
            self.conn.executemany("INSERT INTO vec_chunks (rowid, embedding) VALUES (?, ?)",
                                  [(r["rid"], r["vector"]) for r in rows])
        self.conn.execute("INSERT OR REPLACE INTO vec_meta VALUES ('model', ?)", (self.model_key,))
        count = self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        self.conn.execute("INSERT OR REPLACE INTO vec_meta VALUES ('chunks', ?)", (str(count),))
        self.conn.commit()
        return {"vectors": len(rows), "model": self.model_key, "search": self.search_kind}

    def _stale(self) -> bool:
        count = self.conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        exists = self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'vec_chunks'").fetchone()
        return not exists or self._meta("model") != self.model_key or self._meta("chunks") != str(count)

    def search_by_vector(self, vector, k: int) -> list[tuple[dict, float]]:
        if self._stale():
            self.sync()
        if not self.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'vec_chunks'").fetchone():
            return []
        blob = np.asarray(vector, dtype=np.float32).tobytes()
        hits = self.conn.execute(
            "SELECT v.rowid AS rid, v.distance FROM vec_chunks v WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (blob, k)).fetchall()
        out = []
        for hit in hits:
            row = self.conn.execute(
                "SELECT chunk_id, source_id, page, section, text, token_count, position, language FROM chunks "
                "WHERE rowid = ?", (hit["rid"],)).fetchone()
            if row:
                out.append((dict(row), 1.0 - float(hit["distance"])))
        return out
