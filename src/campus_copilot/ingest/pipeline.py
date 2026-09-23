"""The seven-stage ingestion pipeline: gather → extract → clean → chunk → embed → store → verify.

Every stage reads the previous stage's artifact from `runs/ingest/<run_id>/` and
writes its own, so a run can stop early (`until`), be inspected stage by stage
(`show`), and continue after a failure (`resume`).
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Callable

from .. import config
from . import chunk as chunk_mod
from . import clean as clean_mod
from . import extract as extract_mod
from . import gather as gather_mod
from . import store as store_mod
from .embed import embed_stage
from .verify import verify_stage

STAGES = ["gather", "extract", "clean", "chunk", "embed", "store", "verify"]
ARTIFACTS = {
    "gather": "01_manifest.jsonl", "extract": "02_extracted.jsonl", "clean": "03_clean.jsonl",
    "chunk": "04_chunks.jsonl", "embed": "05_embed_log.jsonl", "store": "06_store.json", "verify": "07_verify.json",
}


class IngestError(RuntimeError):
    pass


def ingest_root() -> Path:
    path = config.runs_dir() / "ingest"
    path.mkdir(parents=True, exist_ok=True)
    return path


def generated_probes_path() -> Path:
    return ingest_root() / "generated_probes.jsonl"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class Run:
    def __init__(self, run_dir: Path, state: dict) -> None:
        self.dir = run_dir
        self.state = state

    @classmethod
    def create(cls, until: str, backends: list[str], profile_name: str) -> "Run":
        run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]
        run_dir = ingest_root() / run_id
        run_dir.mkdir(parents=True)
        state = {"run_id": run_id, "started": dt.datetime.now().isoformat(timespec="seconds"), "finished": None,
                 "until": until, "backends": backends, "profile": profile_name,
                 "stages": {s: {"status": "pending"} for s in STAGES}}
        run = cls(run_dir, state)
        run.save()
        return run

    @classmethod
    def load(cls, run_id: str) -> "Run":
        run_dir = ingest_root() / run_id
        if not (run_dir / "run.json").is_file():
            raise IngestError(f"no ingest run named {run_id!r} under {ingest_root()}")
        return cls(run_dir, json.loads((run_dir / "run.json").read_text(encoding="utf-8")))

    @property
    def run_id(self) -> str:
        return self.state["run_id"]

    def save(self) -> None:
        (self.dir / "run.json").write_text(json.dumps(self.state, indent=2, ensure_ascii=False, default=str),
                                           encoding="utf-8")
        (ingest_root() / "LATEST").write_text(self.run_id, encoding="utf-8")

    def artifact(self, stage: str) -> Path:
        return self.dir / ARTIFACTS[stage]

    def mark(self, stage: str, status: str, stats: dict | None = None, ms: float | None = None, error: str = "") -> None:
        entry = {"status": status}
        if stats is not None:
            entry["stats"] = stats
        if ms is not None:
            entry["ms"] = round(ms, 1)
        if error:
            entry["error"] = error
        self.state["stages"][stage] = entry
        self.save()


def _resolve_backends(settings, store: str | None) -> list[str]:
    from ..rag.stores.base import available_backends

    wanted = store or settings.profile.get("rag.store", "sqlite")
    names = ["sqlite", "sqlite_vec", "chroma"] if wanted == "all" else [wanted]
    available = available_backends()
    usable = [n for n in names if available.get(n, (False, ""))[0]]
    if not usable:
        raise IngestError(f"no usable vector store among {names}: " +
                          "; ".join(f"{n}: {available.get(n, (False, 'unknown'))[1]}" for n in names))
    if "sqlite" not in usable:
        usable.insert(0, "sqlite")  # the default store always stays in sync
    return usable


def run_ingest(settings, until: str | None = None, store: str | None = None, resume: str | None = None,
               gen_probes: bool = False, echo: Callable[[str], None] = print, embed_session=None) -> dict:
    from ..rag.embeddings import get_embedder

    until = until or settings.profile.get("ingest.until", "verify")
    if until not in STAGES:
        raise IngestError(f"unknown stage {until!r}; stages: {', '.join(STAGES)}")
    if resume:
        run = Run.load(resume)
        until = run.state["until"]
        backends = run.state["backends"]
    else:
        backends = _resolve_backends(settings, store)
        run = Run.create(until, backends, settings.profile.name)
    embedder = get_embedder(settings, session=embed_session)
    conn = store_mod.connect()
    last = STAGES.index(until)
    echo(f"Ingest run {run.run_id} (until: {until}; stores: {', '.join(backends)})")
    try:
        for stage in STAGES[: last + 1]:
            if run.state["stages"][stage]["status"] == "done":
                echo(f"  {stage:<8} done earlier; reusing {ARTIFACTS[stage]}")
                continue
            started = time.perf_counter()
            try:
                stats = _run_stage(stage, run, conn, settings, embedder, backends, gen_probes, echo)
            except Exception as exc:
                run.mark(stage, "failed", ms=(time.perf_counter() - started) * 1000, error=f"{type(exc).__name__}: {exc}")
                echo(f"  {stage:<8} FAILED: {exc}")
                echo(f"  resume with: python -m campus_copilot.cli ingest --resume {run.run_id}")
                raise IngestError(f"stage {stage} failed: {exc}") from exc
            run.mark(stage, "done", stats, (time.perf_counter() - started) * 1000)
            echo(f"  {stage:<8} {summary_line(stage, stats)}")
        for stage in STAGES[last + 1:]:
            run.mark(stage, "skipped (until)")
    finally:
        run.state["finished"] = dt.datetime.now().isoformat(timespec="seconds")
        run.save()
        store_mod.record_run(conn, run.run_id, run.state["started"], run.state["finished"], run.state["stages"])
        conn.close()
    return run.state


def _run_stage(stage: str, run: Run, conn: sqlite3.Connection, settings, embedder, backends: list[str],
               gen_probes: bool, echo) -> dict:
    profile = settings.profile
    if stage == "gather":
        records, stats = gather_mod.gather(conn, profile)
        if not embedder.offline:
            echo("  notice: chunk text is sent to NVIDIA's hosted embedding API. Documents that must stay on "
                 "this machine are ingested with --profile offline (lexical and hashing search only).")
        stats["embedder"] = embedder.label
        _write_jsonl(run.artifact("gather"), records)
        return stats
    manifest = _read_jsonl(run.artifact("gather"))
    if stage == "extract":
        units, stats = extract_mod.extract(manifest)
        _write_jsonl(run.artifact("extract"), units)
        return stats
    if stage == "clean":
        units, stats = clean_mod.clean(_read_jsonl(run.artifact("extract")),
                                       strip_headers=bool(profile.get("ingest.clean.strip_headers", True)))
        _write_jsonl(run.artifact("clean"), units)
        return stats
    if stage == "chunk":
        chunks, stats = chunk_mod.chunk(_read_jsonl(run.artifact("clean")), manifest, profile, settings.embed_model)
        _write_jsonl(run.artifact("chunk"), chunks)
        return stats
    chunks = _read_jsonl(run.artifact("chunk"))
    if stage == "embed":
        return embed_stage(conn, manifest, chunks, embedder, int(profile.get("ingest.embed_batch_size", 16)),
                           run.artifact("embed"))
    if stage == "store":
        stats = store_mod.store_stage(conn, manifest, chunks, backends, embedder)
        run.artifact("store").write_text(json.dumps(stats, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        _move_removed_inbox_files(manifest)
        return stats
    if stage == "verify":
        if gen_probes:
            _generate_probes(settings, manifest, chunks, echo)
        stats = verify_stage(conn, manifest, chunks, settings, embedder, generated_probes=generated_probes_path())
        run.artifact("verify").write_text(json.dumps(stats, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return {k: v for k, v in stats.items() if k != "results"}
    raise IngestError(f"unknown stage {stage}")


def _move_removed_inbox_files(manifest: list[dict]) -> None:
    removed_dir = config.runs_dir() / "removed_inbox"
    for doc in manifest:
        path = config.REPO_ROOT / (doc.get("file") or "")
        if doc["status"] == "removed" and doc.get("file", "").startswith("data/inbox/") and path.is_file():
            removed_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), removed_dir / path.name)


def _generate_probes(settings, manifest: list[dict], chunks: list[dict], echo) -> None:
    from ..llm.client import get_llm

    llm = get_llm(settings, role="chat")
    new_docs = [d for d in manifest if d["status"] == "new"]
    existing = {p["source_id"] for p in _read_jsonl(generated_probes_path())}
    rows = []
    for doc in new_docs:
        if doc["source_id"] in existing:
            continue
        first = next((c for c in chunks if c["source_id"] == doc["source_id"]), None)
        if not first:
            continue
        question = llm.generate_probe(doc["title"], first["text"])
        rows.append({"question": question, "source_id": doc["source_id"], "label": "generated",
                     **({"page": first["page"]} if first.get("page") else {})})
    if rows:
        with generated_probes_path().open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        echo(f"  probes   {len(rows)} generated probe(s) added (label: generated)")


# ---------------------------------------------------------------- summaries

def summary_line(stage: str, stats: dict) -> str:
    if stage == "gather":
        flagged = len(stats.get("flagged", {}))
        return (f"{stats['documents']} documents {stats['by_status']}; {flagged} flagged; "
                f"{len(stats.get('skipped', []))} skipped")
    if stage == "extract":
        return (f"{stats['pdf_pages']} PDF pages, {stats['markdown_files']} Markdown files; "
                f"{len(stats['flagged'])} unit(s) flagged")
    if stage == "clean":
        return f"removed {stats['removed']}; characters {stats['chars_before']} -> {stats['chars_after']}"
    if stage == "chunk":
        return (f"{stats['chunks']} chunks ({stats['length_unit']}, size {stats['chunk_size']}, tokenizer "
                f"{stats['tokenizer']}); {len(stats['over_window'])} over the {stats['embed_window']}-token window; "
                f"{len(stats['orphans'])} orphan(s)")
    if stage == "embed":
        return (f"{stats['embedded']} embedded in {stats['batches']} batch(es), {stats['cache_hits']} cache hits, "
                f"{stats['calls']} call(s); model {stats['cache_key']}")
    if stage == "store":
        return (f"+{stats['inserted_chunks']} / -{stats['deleted_chunks']} chunks; total {stats['total_chunks']}; "
                f"backends {', '.join(stats['backends'])}")
    if stage == "verify":
        verdict = "PASS" if stats["passed"] else "FAIL"
        return f"{verdict}: probe hit@{stats['k']} = {stats['hit_rate']} over {stats['probes']} probes"
    return json.dumps(stats)[:200]


def list_runs() -> list[Path]:
    return sorted((p for p in ingest_root().iterdir() if (p / "run.json").is_file()), reverse=True)


def find_artifact(stage: str, doc: str | None = None) -> tuple[Path | None, list[dict] | dict | None]:
    for run_dir in list_runs():
        path = run_dir / ARTIFACTS[stage]
        if not path.is_file():
            continue
        if path.suffix == ".json":
            return path, json.loads(path.read_text(encoding="utf-8"))
        rows = _read_jsonl(path)
        if doc:
            rows = [r for r in rows if r.get("source_id") == doc]
            if not rows:
                continue
        return path, rows
    return None, None


def show(stage: str, doc: str | None = None, echo: Callable[[str], None] = print, limit: int = 40) -> int:
    if stage not in STAGES:
        echo(f"unknown stage {stage!r}; stages: {', '.join(STAGES)}")
        return 1
    path, data = find_artifact(stage, doc)
    if path is None:
        echo(f"no {stage} artifact found{' for ' + doc if doc else ''}; run `cli ingest --until {stage}` first")
        return 1
    echo(f"{stage} artifact: {path}")
    if stage == "gather":
        for r in data:
            flags = f"  flags: {'; '.join(r['flags'])}" if r["flags"] else ""
            echo(f"  {r['status']:<9} {r['source_id']:<32} {r['format']:<3} {r['sha256'][:12]}  "
                 f"{(str(r['pages']) + ' pages') if r.get('pages') else '':<9} licence: {r['licence']}{flags}")
    elif stage in {"extract", "clean"}:
        for r in data[:limit]:
            where = f"p.{r['page']}" if r.get("page") else "body"
            extra = (f" removed {r['removed']}" if stage == "clean" else f" script {r['script']}"
                     + (f"; flags: {'; '.join(r['flags'])}" if r.get("flags") else ""))
            echo(f"  {r['source_id']} {where}: {r.get('chars', r.get('chars_after'))} chars;{extra}")
            echo("    " + r["text"][:240].replace("\n", " | "))
            if stage == "clean" and r.get("samples"):
                echo(f"    removed samples: {r['samples']}")
    elif stage == "chunk":
        for r in data[:limit]:
            where = f"p.{r['page']}" if r.get("page") else f"§ {r['section']}"
            echo(f"  {r['chunk_id']} {r['source_id']} {where} [{r['token_count']} tokens, {r['language']}]")
            echo("    " + r["text"][:200].replace("\n", " | "))
        if len(data) > limit:
            echo(f"  ... {len(data) - limit} more (use --doc SOURCE_ID to narrow)")
    elif stage == "embed":
        for r in data:
            echo("  " + json.dumps(r, ensure_ascii=False))
    else:
        echo(json.dumps({k: v for k, v in data.items() if k != "results"}, indent=2, ensure_ascii=False)[:6000])
    return 0


def remove_document(source_id: str) -> str:
    conn = store_mod.connect()
    try:
        row = conn.execute("SELECT source_id FROM documents WHERE source_id = ?", (source_id,)).fetchone()
        if row:
            conn.execute("UPDATE documents SET status = 'excluded' WHERE source_id = ?", (source_id,))
        else:
            conn.execute("INSERT INTO documents (source_id, status) VALUES (?, 'excluded')", (source_id,))
        conn.commit()
    finally:
        conn.close()
    return f"{source_id} marked for removal; the next `cli ingest` run deletes its chunks from every store."
