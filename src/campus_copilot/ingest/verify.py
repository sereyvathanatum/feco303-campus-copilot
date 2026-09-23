"""Stage 7, verify: consistent row counts, complete chunk metadata, and probe hit@k through retrieval."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..config import DATA_DIR
from .store import fts5_available

PROBE_FILES = [DATA_DIR / "sources" / "probes.jsonl", DATA_DIR / "inbox" / "probes.jsonl"]


def load_probes(extra: Path | None = None, more: list[str] | None = None) -> list[dict]:
    from ..config import REPO_ROOT

    probes: list[dict] = []
    for path in [*PROBE_FILES, *([extra] if extra else []), *[REPO_ROOT / p for p in (more or [])]]:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    probes.append(json.loads(line))
    return probes


def probe_hit(probe: dict, results) -> bool:
    for chunk in results:
        if chunk.source_id != probe["source_id"]:
            continue
        if probe.get("page") and chunk.page != probe["page"]:
            continue
        if probe.get("section_contains") and probe["section_contains"].lower() not in (chunk.section or "").lower():
            continue
        return True
    return False


def verify_stage(conn: sqlite3.Connection, manifest: list[dict], chunks: list[dict], settings, embedder,
                 k: int = 3, generated_probes: Path | None = None) -> dict:
    from ..rag.retrieve import retrieve

    processed = {d["source_id"] for d in manifest if d["status"] in {"new", "changed"}}
    expected = sum(1 for c in chunks if c["source_id"] in processed)
    stored = 0
    for source_id in processed:
        stored += conn.execute("SELECT count(*) FROM chunks WHERE source_id = ?", (source_id,)).fetchone()[0]
    total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    fts_rows = conn.execute("SELECT count(*) FROM chunks_fts").fetchone()[0] if fts5_available() else None
    key = embedder.cache_key("passage")
    with_vectors = conn.execute(
        "SELECT count(*) FROM chunks c JOIN embedding_cache e ON e.chunk_hash = c.chunk_hash AND e.model = ?",
        (key,)).fetchone()[0]
    missing_meta = conn.execute(
        "SELECT count(*) FROM chunks WHERE source_id IS NULL OR (page IS NULL AND (section IS NULL OR section = ''))"
    ).fetchone()[0]
    checks = {
        "chunks_stored_match_chunk_stage": {"ok": stored == expected, "expected": expected, "stored": stored},
        "fts_rows_match_chunks": {"ok": fts_rows is None or fts_rows == total, "fts_rows": fts_rows, "chunks": total},
        "every_chunk_has_a_vector": {"ok": with_vectors == total, "with_vectors": with_vectors, "chunks": total},
        "every_chunk_has_source_and_locator": {"ok": missing_meta == 0, "missing": missing_meta},
    }
    ingested = {r[0] for r in conn.execute("SELECT DISTINCT source_id FROM chunks")}
    extra_files = settings.profile.get("ingest.probes", []) or []
    probes = [p for p in load_probes(generated_probes, extra_files) if p["source_id"] in ingested]
    results = []
    mode = settings.profile.get("rag.mode", "hybrid")
    if mode in {"dense+judge", "dense+rerank"}:
        mode = "hybrid"  # verify measures the index itself, without judge or reranker calls
    for probe in probes:
        found = retrieve(probe["question"], settings, conn=conn, embedder=embedder, mode=mode, k=k)
        hit = probe_hit(probe, found.chunks)
        results.append({"question": probe["question"], "source_id": probe["source_id"], "page": probe.get("page"),
                        "section_contains": probe.get("section_contains"), "label": probe.get("label", "pack"),
                        "hit": hit, "top": [f"{c.source_id} {c.locator}" for c in found.chunks]})
    hit_rate = round(sum(r["hit"] for r in results) / len(results), 3) if results else None
    minimum = float(settings.profile.get("ingest.verify_min_hit_rate", 0.8))
    consistent = all(c["ok"] for c in checks.values())
    passed = consistent and (hit_rate is None or hit_rate >= minimum)
    return {"passed": passed, "checks": checks, "probe_mode": mode, "k": k, "probes": len(results),
            "hit_rate": hit_rate, "min_hit_rate": minimum, "failing_probes": [r for r in results if not r["hit"]],
            "results": results}
