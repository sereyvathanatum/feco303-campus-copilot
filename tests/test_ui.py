"""The Gradio app builds offline and its handlers drive the same copilot as the CLI."""

from __future__ import annotations

import pytest

from campus_copilot.ui import app as ui


@pytest.fixture
def offline_ui(pack_env, monkeypatch):
    monkeypatch.setenv("COPILOT_TODAY", "2026-10-06")
    ui._COPILOTS.clear()
    yield "offline"
    for copilot in ui._COPILOTS.values():
        copilot.close()
    ui._COPILOTS.clear()


def test_app_builds(offline_ui):
    assert ui.build_app("offline") is not None


def test_chat_turn_fills_every_panel(offline_ui):
    state = ui.new_state("offline")
    chat, state, _, decisions, sources, tools, trace, memory, confirm, cancel = ui.send(
        {"text": "What is the yearly tuition fee for Cyber Security?", "files": []}, [], state)
    assert "[academic-info" in chat[-1]["content"] and "STUB" in decisions
    assert "academic-info" in sources and trace and memory["messages_stored"] == 2
    assert confirm["visible"] is False


def test_confirm_and_cancel_buttons_follow_a_pending_write(offline_ui):
    state = ui.new_state("offline")
    chat, state, *_ = ui.send({"text": "Free room with a projector tomorrow 2\u20134 pm? And will it rain then?",
                               "files": []}, [], state)
    chat, state, _, _, _, _, _, _, confirm, cancel = ui.send({"text": "Book it.", "files": []}, chat, state)
    assert confirm["visible"] and cancel["visible"] and "Pending action" in chat[-1]["content"]
    chat, state, *rest = ui.resume(False, chat, state)
    assert chat[-1]["content"].startswith("Cancelled") and rest[-2]["visible"] is False


def test_retrieval_lab_and_knowledge_base_views(offline_ui):
    table, evidence = ui.run_lab("library fines", ["lexical", "dense"], ["sqlite", "sqlite_vec"], 3, "offline")
    assert table == evidence and "| lexical |" in table and "Top-k overlap" in table
    assert [row[0] for row in ui.stage_table()] == ["gather", "extract", "clean", "chunk", "embed", "store", "verify"]
    assert "camtech-prospectus" in ui.document_choices()
    assert "chunks" in ui.document_view("camtech-prospectus")
    assert ui.verify_table()
