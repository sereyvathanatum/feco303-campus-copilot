"""Optional Chroma store (HNSW approximate index, persistent under `runs/chroma/`).

Installed with `pip install -r requirements-optional.txt`; core code never needs it.
Approximate search can return a different top-k from exact search, which E03 measures.
"""

from __future__ import annotations

from ... import config
from .base import KBVectorStore


def availability() -> tuple[bool, str]:
    try:
        import chromadb  # noqa: F401
        import langchain_chroma  # noqa: F401

        return True, "Chroma (HNSW approximate)"
    except ImportError:
        return False, "Chroma not installed (optional: pip install -r requirements-optional.txt)"


class ChromaStore(KBVectorStore):
    name = "chroma"
    search_kind = "HNSW approximate (Chroma)"

    def __init__(self, conn, embedder) -> None:
        super().__init__(conn, embedder)
        import chromadb

        path = config.runs_dir() / "chroma"
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        safe = "".join(ch if ch.isalnum() else "_" for ch in self.model_key)[:50]
        self.collection = self.client.get_or_create_collection(f"kb_{safe}", metadata={"hnsw:space": "cosine"})

    def sync(self, removed_sources: list[str] | None = None) -> dict:
        import numpy as np

        rows = self.conn.execute(
            "SELECT c.chunk_id, c.source_id, e.vector FROM chunks c "
            "JOIN embedding_cache e ON e.chunk_hash = c.chunk_hash AND e.model = ?", (self.model_key,)).fetchall()
        wanted = {r["chunk_id"] for r in rows}
        present = set(self.collection.get(include=[])["ids"])
        stale = sorted(present - wanted)
        if stale:
            self.collection.delete(ids=stale)
        new = [r for r in rows if r["chunk_id"] not in present]
        for start in range(0, len(new), 256):
            part = new[start:start + 256]
            self.collection.add(ids=[r["chunk_id"] for r in part],
                                embeddings=[np.frombuffer(r["vector"], dtype=np.float32).tolist() for r in part],
                                metadatas=[{"source_id": r["source_id"]} for r in part])
        return {"vectors": self.collection.count(), "added": len(new), "deleted": len(stale), "search": self.search_kind}

    def search_by_vector(self, vector, k: int) -> list[tuple[dict, float]]:
        if self.collection.count() == 0:
            self.sync()
        result = self.collection.query(query_embeddings=[list(map(float, vector))], n_results=k)
        ids = result["ids"][0]
        distances = result["distances"][0]
        rows = self.chunk_rows(ids)
        return [(rows[i], 1.0 - float(d)) for i, d in zip(ids, distances) if i in rows]
