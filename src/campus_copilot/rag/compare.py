"""Retrieval Lab: one query through every selected mode × store, side by side (E02, E03).

The chat model and the graph are not involved, so a comparison costs no LLM
tokens; only `dense+judge` calls the decision model.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ingest import store as kb
from .retrieve import MODES, RetrievalResult, retrieve
from .stores.base import available_backends


@dataclass
class Comparison:
    query: str
    k: int
    results: dict[str, RetrievalResult]
    skipped: dict[str, str]

    def overlap(self) -> list[tuple[str, str, int]]:
        keys = list(self.results)
        out = []
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                ids_a = {c.chunk_id for c in self.results[a].chunks}
                ids_b = {c.chunk_id for c in self.results[b].chunks}
                out.append((a, b, len(ids_a & ids_b)))
        return out

    def markdown(self) -> str:
        lines = [f"Query: `{self.query}` (top-{self.k})", "",
                 "| Combination | Rank | Source | Score | Score type | Tokens | Latency ms |",
                 "|---|---:|---|---:|---|---:|---:|"]
        for name, result in self.results.items():
            for c in result.chunks:
                verdict = ""
                if c.judge:
                    verdict = f" (relevant {c.judge.get('relevant', 0):.2f})"
                lines.append(f"| {name} | {c.rank} | {c.source_id} {c.locator} | {c.score:.4f} | {c.score_type}{verdict} "
                             f"| {c.token_count} | {result.latency_ms:.0f} |")
            if not result.chunks:
                lines.append(f"| {name} | - | (no results) | | | | {result.latency_ms:.0f} |")
        for name, reason in self.skipped.items():
            lines.append(f"| {name} | - | skipped: {reason} | | | | |")
        lines += ["", "| Pair | Top-k overlap |", "|---|---:|"]
        lines += [f"| {a} vs {b} | {n}/{self.k} |" for a, b, n in self.overlap()]
        notes = sorted({n for r in self.results.values() for n in r.notes})
        if notes:
            lines += ["", "Notes: " + "; ".join(notes)]
        return "\n".join(lines)


def compare(query: str, settings, modes: list[str] | None = None, stores: list[str] | None = None,
            k: int | None = None, decider=None) -> Comparison:
    k = int(k or settings.profile.get("rag.top_k", 4))
    modes = modes or [m for m in MODES if m != "dense+judge"]
    available = available_backends()
    stores = stores or [name for name, (ok, _) in available.items() if ok]
    results: dict[str, RetrievalResult] = {}
    skipped: dict[str, str] = {}
    conn = kb.connect()
    try:
        for mode in modes:
            for store in (["fts5"] if mode == "lexical" else stores):
                name = mode if mode == "lexical" else f"{mode} @ {store}"
                if mode != "lexical" and not available.get(store, (False, "unknown store"))[0]:
                    skipped[name] = available.get(store, (False, "unknown store"))[1]
                    continue
                results[name] = retrieve(query, settings, conn=conn, mode=mode,
                                         store=None if mode == "lexical" else store, k=k, decider=decider)
    finally:
        conn.close()
    for name, (ok, reason) in available.items():
        if not ok and all(not key.endswith(f"@ {name}") for key in skipped):
            skipped[f"* @ {name}"] = reason
    return Comparison(query, k, results, skipped)
