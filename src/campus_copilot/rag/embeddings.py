"""Embedders shared by both sides of RAG (docs/implementation-plan.md §8.4.4).

The ingest embed stage calls `embed_documents` (`input_type="passage"`); retrieval
calls `embed_query` (`input_type="query"`). `rag.swap_input_type = true` swaps the
two on purpose for E02: no error is raised and retrieval quietly degrades.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from dataclasses import dataclass, field

from langchain_core.embeddings import Embeddings

_WORD = re.compile(r"[a-z0-9]+")
_KHMER_RUN = re.compile(r"[ក-៿]+")
_STOP = set(("a an the of to in on for and or is are be by with at from as it this that what which how "
             "when where who does do can after before per".split()))


class EmbeddingError(RuntimeError):
    pass


@dataclass
class EmbedStats:
    calls: int = 0
    texts: int = 0
    tokens: int = 0
    ms: float = 0.0
    input_types: list[str] = field(default_factory=list)


class BaseEmbedder(Embeddings):
    model: str = "base"
    dim: int = 0
    offline: bool = False
    swap_input_type: bool = False

    def __init__(self) -> None:
        self.stats = EmbedStats()

    def _type(self, requested: str) -> str:
        if not self.swap_input_type:
            return requested
        return "query" if requested == "passage" else "passage"

    def cache_key(self, input_type: str = "passage") -> str:
        """Cache key for stored vectors: model plus the input type actually sent."""
        return f"{self.model}|{self._type(input_type)}"

    def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        raise NotImplementedError

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed(texts, self._type("passage"))

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text], self._type("query"))[0]

    @property
    def label(self) -> str:
        return f"{self.model}{' (offline hashing encoder)' if self.offline else ''}"


class HashingEmbedder(BaseEmbedder):
    """Offline encoder: hashed word unigrams and bigrams plus Khmer character trigrams, L2-normalised.

    Deterministic (MD5-based hashing) and symmetric, so the input type has no effect.
    """

    model = "hashing-512-v1"
    dim = 512
    offline = True

    def _features(self, text: str) -> list[str]:
        lower = text.lower()
        words = [w for w in _WORD.findall(lower) if w not in _STOP]
        feats = words + [f"{a}_{b}" for a, b in zip(words, words[1:])]
        for run in _KHMER_RUN.findall(text):
            feats += [run[i:i + 3] for i in range(max(1, len(run) - 2))]
        return feats

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat in self._features(text):
            digest = hashlib.md5(feat.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "little") % self.dim
            vec[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        started = time.perf_counter()
        out = [self._vector(t) for t in texts]
        self.stats.calls += 1
        self.stats.texts += len(texts)
        self.stats.ms += (time.perf_counter() - started) * 1000
        self.stats.input_types.append(input_type)
        return out


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.interval = 60.0 / per_minute if per_minute > 0 else 0.0
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._last + self.interval - now
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


class NimEmbedder(BaseEmbedder):
    """NVIDIA NIM embeddings over plain HTTP; the request body stays visible and testable.

    `truncate="NONE"` makes an over-long input fail loudly instead of being cut silently.
    """

    offline = False

    def __init__(self, api_key: str, model: str, base_url: str, session=None, timeout: float = 60.0,
                 requests_per_minute: int = 35, retries: int = 2) -> None:
        super().__init__()
        import requests

        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.limiter = RateLimiter(requests_per_minute)
        self.dim = 0

    def request_body(self, texts: list[str], input_type: str) -> dict:
        return {"model": self.model, "input": texts, "input_type": input_type,
                "truncate": "NONE", "encoding_format": "float"}

    def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        body = self.request_body(texts, input_type)
        last_error = ""
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            started = time.perf_counter()
            try:
                response = self.session.post(f"{self.base_url}/embeddings", json=body, timeout=self.timeout,
                                             headers={"Authorization": f"Bearer {self.api_key}",
                                                      "Accept": "application/json"})
            except Exception as exc:  # network errors are retried, then reported
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5 * 2 ** attempt)
                continue
            self.stats.ms += (time.perf_counter() - started) * 1000
            if response.status_code == 200:
                payload = response.json()
                vectors = [item["embedding"] for item in sorted(payload["data"], key=lambda d: d["index"])]
                self.dim = len(vectors[0]) if vectors else self.dim
                self.stats.calls += 1
                self.stats.texts += len(texts)
                self.stats.tokens += int(payload.get("usage", {}).get("prompt_tokens", 0))
                self.stats.input_types.append(input_type)
                return vectors
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            time.sleep(0.5 * 2 ** attempt)
        raise EmbeddingError(last_error)


def get_embedder(settings, session=None) -> BaseEmbedder:
    """NIM embedder when a NIM key is present and the profile allows live calls; else the hashing encoder."""
    profile = settings.profile
    if settings.has_nim and settings.nemotron_api_key:
        embedder: BaseEmbedder = NimEmbedder(
            settings.nemotron_api_key, settings.embed_model, settings.nvidia_base_url, session=session,
            timeout=settings.nim_timeout, requests_per_minute=int(profile.get("ingest.requests_per_minute", 35)))
    else:
        embedder = HashingEmbedder()
    embedder.swap_input_type = bool(profile.get("rag.swap_input_type", False))
    return embedder
