"""Step 6 checkpoint: remember the conversation."""

import pytest

from .conftest import demo_board, offline_copilot, spans

pytestmark = pytest.mark.step06


def test_follow_up_rewritten_and_threads_isolated(pack_env):
    board, copilot = demo_board(6)
    assert board.passed == board.expected(6) == [1, 2, 3]
    query = board.outcomes[1].result.query
    assert "master's degree" in query["rewritten"] and query["original"] == "And for a master's degree?"
    assert all(s.get("gate") == "rag.condense_query = always" or not s.get("ran") for s in spans(copilot, board, "condense_query"))
    fresh = offline_copilot(6)
    try:
        result = fresh.ask("And for a master's degree?", thread_id="another-thread")
        assert not (result.query or {}).get("rewritten")  # a new thread has no history to resolve against
    finally:
        fresh.close()


def test_model_window_is_respected(pack_env):
    copilot = offline_copilot(6, **{"memory.window_turns": 1})
    try:
        for message in ["What is the pass mark for a course?", "What is the library fine?", "And for lost books?"]:
            result = copilot.ask(message, thread_id="window")
        begin = [s for s in copilot.trace(result.trace_id) if s["span"] == "begin"][0]
        assert begin["history_messages"] == 4 and begin["window_messages"] <= 2 and begin["dropped_messages"] >= 2
    finally:
        copilot.close()
