"""Vector-store backends behind LangChain's `VectorStore` interface, plus the factory.

Every backend reads the same chunks and cached embeddings from `kb.db`, so a
comparison between backends isolates the store (docs/implementation-plan.md §8.4.3).
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

CHUNK_COLUMNS = "c.chunk_id, c.source_id, c.page, c.section, c.text, c.token_count, c.position, c.language"


class KBVectorStore(VectorStore):
    """Base class: subclasses implement `sync` and `search_by_vector`."""

    name = "base"
    search_kind = "exact cosine"

    def __init__(self, conn: sqlite3.Connection, embedder) -> None:
        self.conn = conn
        self.embedder = embedder
        self.model_key = embedder.cache_key("passage")

    @property
    def embeddings(self):
        return self.embedder

    # -- to implement ------------------------------------------------------
    def sync(self, removed_sources: list[str] | None = None) -> dict:
        raise NotImplementedError

    def search_by_vector(self, vector, k: int) -> list[tuple[dict, float]]:
        raise NotImplementedError

    # -- shared helpers ----------------------------------------------------
    def chunk_rows(self, chunk_ids: list[str]) -> dict[str, dict]:
        rows: dict[str, dict] = {}
        for start in range(0, len(chunk_ids), 500):
            part = chunk_ids[start:start + 500]
            marks = ",".join("?" for _ in part)
            for row in self.conn.execute(f"SELECT {CHUNK_COLUMNS} FROM chunks c WHERE c.chunk_id IN ({marks})", part):
                rows[row["chunk_id"]] = dict(row)
        return rows

    def search(self, query: str, k: int = 4) -> list[tuple[dict, float]]:
        return self.search_by_vector(self.embedder.embed_query(query), k)

    # -- LangChain VectorStore interface ----------------------------------
    def similarity_search_with_score(self, query: str, k: int = 4, **kwargs: Any) -> list[tuple[Document, float]]:
        return [(self._to_document(row), score) for row, score in self.search(query, k)]

    def similarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        return [doc for doc, _ in self.similarity_search_with_score(query, k)]

    def similarity_search_by_vector(self, embedding: list[float], k: int = 4, **kwargs: Any) -> list[Document]:
        return [self._to_document(row) for row, _ in self.search_by_vector(embedding, k)]

    def add_texts(self, texts: Iterable[str], metadatas: list[dict] | None = None, **kwargs: Any) -> list[str]:
        """Add ad-hoc texts as chunks of the source `adhoc` (used by `from_texts` and tests)."""
        from ...ingest import store as kb
        from ...ingest.chunk import chunk_hash, chunk_id

        texts = list(texts)
        metadatas = metadatas or [{} for _ in texts]
        ids = []
        vectors = self.embedder.embed_documents(texts)
        for position, (text, meta, vector) in enumerate(zip(texts, metadatas, vectors)):
            source_id = meta.get("source_id", "adhoc")
            section = meta.get("section", "adhoc")
            cid = chunk_id(source_id, f"s:{section}", text)
            digest = chunk_hash(text)
            self.conn.execute("INSERT OR REPLACE INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                              (cid, source_id, meta.get("page"), section, text, len(text.split()), position,
                               meta.get("language", "en"), digest))
            kb.put_vectors(self.conn, self.model_key, [(digest, vector)])
            ids.append(cid)
        self.conn.commit()
        self.sync()
        return ids

    @classmethod
    def from_texts(cls, texts: list[str], embedding, metadatas: list[dict] | None = None, **kwargs: Any):
        from ...ingest import store as kb

        conn = kwargs.get("conn") or kb.connect(kwargs.get("path"))
        store = cls(conn, embedding)
        store.add_texts(texts, metadatas)
        return store

    @staticmethod
    def _to_document(row: dict) -> Document:
        return Document(page_content=row["text"], id=row["chunk_id"],
                        metadata={k: row.get(k) for k in ("chunk_id", "source_id", "page", "section",
                                                          "token_count", "position", "language")})


def available_backends() -> dict[str, tuple[bool, str]]:
    from . import chroma, sqlite_vec

    return {"sqlite": (True, "SQLite + NumPy exact cosine"),
            "sqlite_vec": sqlite_vec.availability(),
            "chroma": chroma.availability()}


def get_store(name: str, embedder, conn: sqlite3.Connection | None = None) -> KBVectorStore:
    from ...ingest import store as kb

    conn = conn or kb.connect()
    if name == "sqlite":
        from .sqlite_numpy import SqliteNumpyStore

        return SqliteNumpyStore(conn, embedder)
    if name == "sqlite_vec":
        from .sqlite_vec import SqliteVecStore

        return SqliteVecStore(conn, embedder)
    if name == "chroma":
        from .chroma import ChromaStore

        return ChromaStore(conn, embedder)
    raise ValueError(f"unknown store {name!r}; choose sqlite, sqlite_vec, or chroma")
