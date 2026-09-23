"""Retrieval, stores, embeddings, the model client, grounded answers, and follow-up rewriting (offline)."""

from __future__ import annotations

import pytest
import requests
from fakes import FakeResponse, RecordingSession
from langchain_core.messages import AIMessage, HumanMessage

from campus_copilot import config
from campus_copilot.graph.memory import model_window
from campus_copilot.ingest import store as kb
from campus_copilot.llm import nim
from campus_copilot.llm.client import LLM
from campus_copilot.llm.stub import StubClient
from campus_copilot.rag import condense
from campus_copilot.rag.answer import answer
from campus_copilot.rag.embeddings import HashingEmbedder, NimEmbedder
from campus_copilot.rag.retrieve import MODES, retrieve
from campus_copilot.rag.stores.base import available_backends, get_store
from campus_copilot.schemas import ABSTAIN_TEXT


def offline():
    return config.get_settings("offline")


# ------------------------------------------------------------ embedding contract

def assert_embedding_contract(embedder, session: RecordingSession) -> None:
    """Stored chunks are embedded as `passage`, searches as `query`, with truncate=NONE."""
    embedder.embed_documents(["a stored chunk"])
    embedder.embed_query("a search")
    sent = [r["json"] for r in session.requests]
    assert [b["input_type"] for b in sent] == ["passage", "query"], "input_type swapped or missing"
    assert all(b["truncate"] == "NONE" and b["model"] == "nvidia/nemotron-3-embed-1b" for b in sent)


def _nim_embedder(swap: bool):
    vector = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}], "usage": {"prompt_tokens": 3}}
    session = RecordingSession(default=FakeResponse(200, vector))
    embedder = NimEmbedder("nvapi-" + "x" * 30, "nvidia/nemotron-3-embed-1b", "https://example.invalid/v1",
                           session=session, requests_per_minute=0)
    embedder.swap_input_type = swap
    return embedder, session


def test_embedding_contract_holds():
    embedder, session = _nim_embedder(swap=False)
    assert_embedding_contract(embedder, session)


def test_embedding_contract_catches_a_swapped_input_type():
    embedder, session = _nim_embedder(swap=True)
    with pytest.raises(AssertionError, match="input_type"):
        assert_embedding_contract(embedder, session)
    assert embedder.cache_key("passage").endswith("|query")


def test_nim_embedder_retries_then_reports_errors_as_exceptions():
    ok = FakeResponse(200, {"data": [{"index": 0, "embedding": [1.0]}], "usage": {}})
    session = RecordingSession([FakeResponse(503, text="busy"), ok])
    embedder = NimEmbedder("k", "m", "https://example.invalid", session=session, requests_per_minute=0)
    assert embedder.embed_query("x") == [1.0]
    assert len(session.requests) == 2


def test_hashing_encoder_is_deterministic_and_normalised():
    enc = HashingEmbedder()
    a, b = enc.embed_query("late assignments penalty"), enc.embed_query("late assignments penalty")
    assert a == b and abs(sum(v * v for v in a) - 1.0) < 1e-6


# -------------------------------------------------------------------- stores

def test_store_parity_sqlite_and_sqlite_vec(pack_env):
    if not available_backends()["sqlite_vec"][0]:
        pytest.skip("sqlite-vec cannot load in this Python build")
    conn = kb.connect()
    embedder = HashingEmbedder()
    exact, vec = get_store("sqlite", embedder, conn), get_store("sqlite_vec", embedder, conn)
    for query in ["penalty for late assignments", "library opening hours", "replacement ID card fee",
                  "what is a Noul", "Wi-Fi password reset"]:
        a = [row["chunk_id"] for row, _ in exact.search(query, 5)]
        b = [row["chunk_id"] for row, _ in vec.search(query, 5)]
        assert a == b, query


def test_chroma_overlap_is_reported_when_installed(pack_env):
    if not available_backends()["chroma"][0]:
        pytest.skip("Chroma is an optional extra")
    conn = kb.connect()
    embedder = HashingEmbedder()
    exact, approx = get_store("sqlite", embedder, conn), get_store("chroma", embedder, conn)
    a = {row["chunk_id"] for row, _ in exact.search("library fines", 5)}
    b = {row["chunk_id"] for row, _ in approx.search("library fines", 5)}
    assert len(a & b) >= 3


def test_store_implements_vectorstore_interface(pack_env):
    store = get_store("sqlite", HashingEmbedder(), kb.connect())
    docs = store.similarity_search("late assignments", k=3)
    assert docs and all({"source_id", "page", "section", "token_count"} <= set(d.metadata) for d in docs)


# ---------------------------------------------------------------- retrieval

@pytest.mark.parametrize("mode", [m for m in MODES if m != "dense+judge"])
def test_every_mode_returns_labelled_results(pack_env, mode):
    result = retrieve("What is the penalty for late assignments?", offline(), mode=mode, k=3)
    assert result.mode == mode and result.latency_ms >= 0
    assert result.chunks and all(c.score_type for c in result.chunks)
    assert any(c.source_id == "campus-handbook" and c.page == 6 for c in result.chunks)


def test_offline_rerank_uses_the_local_heuristic_and_orders_best_first(pack_env):
    result = retrieve("library fines", offline(), mode="hybrid+rerank", k=5)
    assert result.candidates > 5 and len(result.chunks) == 5
    assert any("reranked" in n and "local" in n for n in result.notes)
    scores = [c.score for c in result.chunks]
    assert scores == sorted(scores, reverse=True) and [c.rank for c in result.chunks] == [1, 2, 3, 4, 5]
    top = result.chunks[0].signals
    assert top["reranker"] == "local" and {"first_stage_rank", "rrf", "relevance"} <= set(top)


def test_nim_reranker_request_and_order(pack_env):
    from campus_copilot.rag.rerank import rerank

    settings = offline()
    candidates = retrieve("library fines", settings, mode="hybrid", k=4).chunks
    session = RecordingSession([FakeResponse(200, {"rankings": [
        {"index": 2, "logit": 3.0}, {"index": 0, "logit": 1.0}, {"index": 3, "logit": -2.0}, {"index": 1, "logit": -5.0}]})])
    settings.nvidia_api_key = settings.nemotron_api_key = "nvapi-" + "x" * 40
    settings.profile.data.setdefault("app", {})["force_offline"] = False
    outcome = rerank(settings, "library fines", candidates, k=3, session=session, backend="nim")
    body = session.requests[0]["json"]
    assert body["query"] == {"text": "library fines"} and len(body["passages"]) == 4 and body["truncate"] == "END"
    assert [c.signals["first_stage_rank"] for c in outcome.chunks] == [3, 1, 4]
    assert outcome.chunks[0].signals["relevance"] > 0.9


def test_failed_nim_reranker_falls_back_to_local(pack_env):
    from campus_copilot.rag.rerank import rerank

    settings = offline()
    candidates = retrieve("library fines", settings, mode="hybrid", k=4).chunks
    settings.nvidia_api_key = settings.nemotron_api_key = "nvapi-" + "x" * 40
    settings.profile.data.setdefault("app", {})["force_offline"] = False
    outcome = rerank(settings, "library fines", candidates, k=2,
                     session=RecordingSession([FakeResponse(410, {"title": "Gone"})]), backend="nim")
    assert outcome.backend == "local" and len(outcome.chunks) == 2
    assert any("HTTP 410" in n for n in outcome.notes)


def test_jev_reranker_keeps_verdicts_for_the_passage_filter(pack_env):
    from campus_copilot.decisions.base import get_decider
    from campus_copilot.rag.rerank import rerank

    settings = offline()
    candidates = retrieve("library fines", settings, mode="hybrid", k=4).chunks
    decider = get_decider(settings, kind="keyword")
    outcome = rerank(settings, "library fines", candidates, k=4, decider=decider, backend="jev")
    assert all(c.judge and "has_answer" in c.judge for c in outcome.chunks)


def test_passages_carry_rank_and_relevance_into_the_prompt(pack_env):
    from campus_copilot.rag.answer import passages_for

    chunks = retrieve("library fines", offline(), mode="hybrid+rerank", k=3).chunks
    passages = passages_for(chunks)
    assert [p["rank"] for p in passages] == [1, 2, 3] and all("relevance" in p for p in passages)


def test_lexical_matches_codes_and_numbers(pack_env):
    result = retrieve("extension 999", offline(), mode="lexical", k=3)
    assert {(c.source_id, c.page) for c in result.chunks[:2]} == {("campus-handbook", 18), ("campus-handbook", 19)}


# -------------------------------------------------------------- model client

def _chat_payload(content: str, **extra):
    return {"model": "gemma-4-31b-it", "choices": [{"message": {"content": content, **extra}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 4}}


def test_client_strips_thoughts_and_retries_503():
    session = RecordingSession([FakeResponse(503, text="high demand"),
                                FakeResponse(200, [_chat_payload("<thought>step one</thought>391")])])
    client = nim.OpenAICompatClient("google", "https://example.invalid", "k", "gemma-4-31b-it", session=session)
    reply = client.complete([{"role": "user", "content": "17 * 23?"}], max_tokens=16)
    assert reply.text == "391" and reply.thought_chars > 0
    assert session.requests[0]["json"]["max_tokens"] >= 4096  # thought tokens count against the budget


def test_client_drops_response_format_when_unsupported():
    session = RecordingSession([FakeResponse(400, text="response_format unsupported"),
                                FakeResponse(200, _chat_payload('{"x": 1}'))])
    client = nim.OpenAICompatClient("nim", "https://example.invalid", "k", "m", session=session)
    client.complete([{"role": "user", "content": "json"}], json_mode=True)
    assert "response_format" in session.requests[0]["json"] and "response_format" not in session.requests[1]["json"]


def test_timeout_falls_back_to_stub_with_label():
    nim.reset_health()
    session = RecordingSession([requests.Timeout("slow")])
    client = nim.OpenAICompatClient("nim", "https://example.invalid", "k", "m", session=session, timeout=1)
    llm = LLM([client, StubClient("fallback")], offline())
    reply = llm.small_reply("hello")
    assert reply.stub and reply.notes == ["STUB (nim unavailable)"]
    assert not nim.is_healthy(client.name)  # the next call skips the slow provider at once
    nim.reset_health()


def test_empty_thought_only_reply_is_a_failure():
    session = RecordingSession([FakeResponse(200, _chat_payload("<thought>long thinking</thought>"))])
    client = nim.OpenAICompatClient("google", "https://example.invalid", "k", "m", session=session, retries=0)
    with pytest.raises(nim.LLMError, match="thinking"):
        client.complete([{"role": "user", "content": "x"}])


def test_parse_json_object_is_tolerant():
    assert nim.parse_json_object('```json\n{"a": {"b": "}"}}\n```') == {"a": {"b": "}"}}
    assert nim.parse_json_object("no json here") is None


# ---------------------------------------------------------- grounded answers

def test_stub_answers_turn_one_and_abstains_on_turn_three(pack_env):
    settings = offline()
    llm = LLM([StubClient()], settings)
    q1 = "What happens after more than three missed lab sessions?"
    a1 = answer(q1, retrieve(q1, settings).chunks, llm)
    assert not a1.grounded.abstained and "[campus-handbook p.4]" in a1.text
    q3 = "What is the cafeteria menu on Friday?"
    a3 = answer(q3, retrieve(q3, settings).chunks, llm)
    assert a3.grounded.abstained and a3.text == ABSTAIN_TEXT


def test_unknown_citations_are_dropped():
    class Canned(StubClient):
        def complete(self, messages, **kw):
            reply = super().complete(messages, **kw)
            reply.text = ('{"answer": "Fines are 500 riel.", "citations": [{"source_id": "made-up", "page": 9}, '
                          '{"source_id": "campus-handbook", "page": 11}], "abstained": false}')
            return reply

    llm = LLM([Canned()], offline())
    passages = [{"source_id": "campus-handbook", "page": 11, "section": None, "text": "500 riel per day"}]
    grounded, reply = llm.grounded_answer("fine?", passages)
    assert [c.source_id for c in grounded.citations] == ["campus-handbook"]
    assert any("made-up" in n for n in reply.notes)


def test_no_passages_abstains_without_a_model_call():
    llm = LLM([StubClient()], offline())
    result = answer("anything", [], llm)
    assert result.grounded.abstained and not llm.log.replies


# --------------------------------------------------------------- condensing

def test_condense_keeps_codes_or_falls_back():
    class Dropper(StubClient):
        def complete(self, messages, **kw):
            reply = super().complete(messages, **kw)
            reply.text = "When is the lab?"
            return reply

    llm = LLM([Dropper()], offline())
    history = [{"role": "user", "content": "Where is the FECO303 lecture?"}, {"role": "assistant", "content": "A-101"}]
    result = condense.condense("And the FECO303 lab?", history, llm, mode="always")
    assert result.fallback and result.query == "And the FECO303 lab?"


def test_condense_gate_modes():
    history = [{"role": "user", "content": "x"}]
    assert condense.gate("off", history, "handbook", 0.9, 0.5)[0] is False
    assert condense.gate("always", history, "rooms", None, 0.5)[0] is True
    assert condense.gate("jev_gated", history, "handbook", 0.8, 0.5)[0] is True
    assert condense.gate("jev_gated", history, "handbook", 0.2, 0.5)[0] is False
    assert condense.gate("jev_gated", [], "handbook", 0.9, 0.5)[0] is False


def test_stub_rewrites_the_demo_follow_up():
    llm = LLM([StubClient()], offline())
    history = [{"role": "user", "content": "What happens after more than three missed lab sessions?"}]
    result = condense.condense("And for late assignments?", history, llm, mode="always")
    assert result.rewritten and "late assignments" in result.rewritten
    assert result.original == "And for late assignments?"


# ------------------------------------------------------------- model window

def test_window_keeps_system_and_respects_limits():
    settings = config.get_settings("offline", {"memory.window_turns": 2, "memory.max_tokens": 60})
    history = []
    for i in range(6):
        history += [HumanMessage(f"question number {i} " + "word " * 10), AIMessage(f"answer {i} " + "word " * 10)]
    window = model_window(history, settings, system="System rules.")
    assert window.tokens <= 60 + 20  # the system message is always kept on top of the budget check
    assert window.messages and isinstance(window.messages[0], HumanMessage)
    assert len(window.messages) <= 4 and window.dropped_messages >= 8
    assert window.messages[-1].content.startswith("answer 5")
