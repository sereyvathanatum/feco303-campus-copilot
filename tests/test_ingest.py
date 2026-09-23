"""Ingestion stages on a tiny fixture set (2 PDFs, 3 Markdown files); offline, builtin tokenizer."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campus_copilot import config
from campus_copilot.ingest import pipeline
from campus_copilot.ingest import store as kb
from campus_copilot.ingest.chunk import ORPHAN_TOKENS
from campus_copilot.rag.embeddings import EmbeddingError, HashingEmbedder

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"
CHUNK_SIZE = 60


@pytest.fixture
def src(tmp_path, runs_dir):
    folder = tmp_path / "src"
    shutil.copytree(FIXTURES, folder)
    return folder


def make_settings(src: Path, **extra):
    overrides = {"ingest.sources": [str(src)], "ingest.probes": [str(src / "probes.jsonl")],
                 "rag.chunk_size": CHUNK_SIZE, "rag.chunk_overlap": 10, **extra}
    return config.get_settings("offline", overrides)


def run(settings, **kwargs):
    return pipeline.run_ingest(settings, echo=lambda _: None, **kwargs)


def artifact(state: dict, stage: str):
    path = pipeline.ingest_root() / state["run_id"] / pipeline.ARTIFACTS[stage]
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_full_run_passes_and_counts_chain(src):
    state = run(make_settings(src))
    stages = state["stages"]
    assert all(stages[s]["status"] == "done" for s in pipeline.STAGES)
    assert stages["verify"]["stats"]["passed"], stages["verify"]["stats"]
    docs = artifact(state, "gather")
    assert len(docs) == 5 and {d["status"] for d in docs} == {"new"}
    extracted, cleaned, chunks = artifact(state, "extract"), artifact(state, "clean"), artifact(state, "chunk")
    assert len(extracted) == 3 + 3 + 3  # 3 + 3 PDF pages, 3 Markdown files
    assert len(cleaned) == len(extracted)
    conn = kb.connect()
    assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == len(chunks)
    assert all(c["source_id"] and (c["page"] or c["section"]) for c in chunks)


def test_pdf_pages_are_one_based_and_cleaned(src):
    state = run(make_settings(src), until="clean")
    pages = [u for u in artifact(state, "extract") if u["source_id"] == "fixture-rules"]
    assert [p["page"] for p in pages] == [1, 2, 3]
    clean = {u["page"]: u for u in artifact(state, "clean") if u["source_id"] == "fixture-rules"}
    text = "\n".join(u["text"] for u in clean.values())
    assert "Fixture Rules Booklet" not in text
    assert "Page 1 of 3" not in text
    assert "registration" in clean[1]["text"]
    assert clean[1]["removed"]["hyphen_joins"] == 1


def test_near_empty_page_is_flagged(src):
    state = run(make_settings(src), until="extract")
    sparse = {u["page"]: u for u in artifact(state, "extract") if u["source_id"] == "fixture-sparse"}
    assert any("near-empty" in f for f in sparse[2]["flags"])


def test_markdown_sections_and_comments(src):
    state = run(make_settings(src), until="chunk")
    cleaned = [u for u in artifact(state, "clean") if u["source_id"] == "fixture-lockers-faq"][0]
    assert "HTML comment" not in cleaned["text"] and cleaned["removed"]["html_comments"] == 1
    sections = {c["section"] for c in artifact(state, "chunk") if c["source_id"] == "fixture-lockers-faq"}
    assert "Renting › How is a locker rented?" in sections


def test_no_pdf_chunk_crosses_a_page_and_sizes_hold(src):
    state = run(make_settings(src), until="chunk")
    pages = {(u["source_id"], u["page"]): u["text"] for u in artifact(state, "clean") if u["format"] == "pdf"}
    for c in artifact(state, "chunk"):
        assert c["token_count"] <= CHUNK_SIZE + ORPHAN_TOKENS
        if c["page"]:
            assert c["text"] in pages[(c["source_id"], c["page"])]


def test_window_check_lists_chunks_over_the_embedder_window(src):
    state = run(make_settings(src, **{"rag.embed_max_tokens": 20}), until="chunk")
    over = state["stages"]["chunk"]["stats"]["over_window"]
    assert over and all(o["token_count"] > 20 and o["dropped_text"] for o in over)


def test_incremental_runs(src):
    settings = make_settings(src)
    first = run(settings)
    assert first["stages"]["embed"]["stats"]["embedded"] > 0
    second = run(settings)
    assert second["stages"]["embed"]["stats"]["calls"] == 0
    assert second["stages"]["gather"]["stats"]["by_status"] == {"unchanged": 5}
    doc = src / "fixture-printing.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n## Binding\n\nThesis binding takes two working days.\n",
                   encoding="utf-8")
    third = run(settings)
    printing_chunks = [c for c in artifact(third, "chunk") if c["source_id"] == "fixture-printing"]
    assert third["stages"]["gather"]["stats"]["by_status"] == {"changed": 1, "unchanged": 4}
    assert 0 < third["stages"]["embed"]["stats"]["embedded"] <= len(printing_chunks)
    assert third["stages"]["verify"]["stats"]["passed"]


def test_changed_chunk_settings_rechunk_unchanged_files(src):
    run(make_settings(src))
    again = run(make_settings(src, **{"ingest.tables": "rows"}))
    gather = again["stages"]["gather"]["stats"]
    assert gather["by_status"] == {"changed": 5}
    assert all("chunk settings or chunker version changed: re-chunked" in f for f in gather["flagged"].values())
    assert run(make_settings(src, **{"ingest.tables": "rows"}))["stages"]["gather"]["stats"]["by_status"] == {
        "unchanged": 5}


def test_removed_document_leaves_every_backend(src):
    settings = make_settings(src)
    run(settings, store="all")
    conn = kb.connect()
    before = conn.execute("SELECT count(*) FROM chunks WHERE source_id = 'fixture-printing'").fetchone()[0]
    assert before > 0
    pipeline.remove_document("fixture-printing")
    state = run(settings, store="all")
    assert "fixture-printing" in state["stages"]["store"]["stats"]["documents_removed"]
    conn = kb.connect()
    assert conn.execute("SELECT count(*) FROM chunks WHERE source_id = 'fixture-printing'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM chunks_fts WHERE source_id = 'fixture-printing'").fetchone()[0] == 0
    backends = state["stages"]["store"]["stats"]["backends"]
    total = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
    assert all(b["vectors"] == total for b in backends.values())
    again = run(settings)
    assert again["stages"]["gather"]["stats"]["by_status"].get("new", 0) == 0


def test_gather_flags_unknown_licence_and_duplicates(src):
    shutil.copyfile(src / "fixture-rules.pdf", src / "copy-of-rules.pdf")
    state = run(make_settings(src), until="gather")
    flagged = state["stages"]["gather"]["stats"]["flagged"]
    assert "licence unknown" in flagged["fixture-nolicence"]
    duplicates = [f for sid in ("copy-of-rules", "fixture-rules") for f in flagged.get(sid, []) if "duplicate of" in f]
    assert duplicates == ["duplicate of copy-of-rules (same SHA-256)"]  # the first file scanned is the original


def test_resume_after_failed_batch(src, monkeypatch):
    settings = make_settings(src, **{"ingest.embed_batch_size": 2})
    original = HashingEmbedder.embed
    calls = {"n": 0}

    def flaky(self, texts, input_type):
        calls["n"] += 1
        if calls["n"] == 2:
            raise EmbeddingError("simulated HTTP 503")
        return original(self, texts, input_type)

    monkeypatch.setattr(HashingEmbedder, "embed", flaky)
    with pytest.raises(pipeline.IngestError):
        run(settings, **{})
    failed = pipeline.Run.load(pipeline.list_runs()[0].name)
    assert failed.state["stages"]["embed"]["status"] == "failed"
    assert failed.state["stages"]["chunk"]["status"] == "done"
    resumed = run(settings, resume=failed.run_id)
    assert resumed["stages"]["embed"]["stats"]["cache_hits"] > 0  # the batch before the failure was kept
    assert resumed["stages"]["verify"]["stats"]["passed"]


def test_show_prints_stage_artifacts(src):
    run(make_settings(src), until="chunk")
    lines: list[str] = []
    assert pipeline.show("chunk", "fixture-rules", echo=lines.append) == 0
    assert any("fixture-rules p.1" in line for line in lines)
