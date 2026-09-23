"""Default store: vectors from `chunks` + `embedding_cache`, exact cosine top-k in NumPy.

The whole search is a matrix-vector product over normalised vectors, which shows
the maths behind a vector store with no extra install.
"""

from __future__ import annotations

import numpy as np

from .base import KBVectorStore


class SqliteNumpyStore(KBVectorStore):
    name = "sqlite"
    search_kind = "exact cosine (NumPy)"

    def __init__(self, conn, embedder) -> None:
        super().__init__(conn, embedder)
        self._ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._version: tuple[int, int] | None = None

    def _current_version(self) -> tuple[int, int]:
        row = self.conn.execute(
            "SELECT count(*), coalesce(sum(length(c.chunk_id)), 0) FROM chunks c "
            "JOIN embedding_cache e ON e.chunk_hash = c.chunk_hash AND e.model = ?", (self.model_key,)).fetchone()
        return int(row[0]), int(row[1])

    def _load(self) -> None:
        rows = self.conn.execute(
            "SELECT c.chunk_id, e.vector FROM chunks c "
            "JOIN embedding_cache e ON e.chunk_hash = c.chunk_hash AND e.model = ? ORDER BY c.chunk_id",
            (self.model_key,)).fetchall()
        self._ids = [r["chunk_id"] for r in rows]
        if rows:
            matrix = np.vstack([np.frombuffer(r["vector"], dtype=np.float32) for r in rows])
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._matrix = matrix / norms
        else:
            self._matrix = None
        self._version = self._current_version()

    def sync(self, removed_sources: list[str] | None = None) -> dict:
        self._load()
        return {"vectors": len(self._ids), "model": self.model_key, "search": self.search_kind}

    def search_by_vector(self, vector, k: int) -> list[tuple[dict, float]]:
        if self._matrix is None or self._version != self._current_version():
            self._load()
        if self._matrix is None:
            return []
        query = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(query) or 1.0
        scores = self._matrix @ (query / norm)
        top = np.argsort(-scores)[:k]
        ids = [self._ids[i] for i in top]
        rows = self.chunk_rows(ids)
        return [(rows[self._ids[i]], float(scores[i])) for i in top if self._ids[i] in rows]
