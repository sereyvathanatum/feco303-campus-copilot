"""Step 9 checkpoint: agent loop and safe writes."""

import pytest

from campus_copilot.db import connection, queries

from .conftest import demo_board, offline_copilot

pytestmark = pytest.mark.step09

TURN_8 = "Free room with a projector tomorrow 2\u20134 pm? And will it rain then?"


def test_agent_and_write_scoreboard(pack_env):
    board, _ = demo_board(9)
    assert board.passed == board.expected(9)
    assert len(board.passed) == 13
    turn9 = board.outcomes[8]
    assert turn9.result.kind == "confirm" and turn9.after_confirm.answer.startswith("Cancelled")


def test_loop_stops_at_its_limit(pack_env):
    copilot = offline_copilot(9, **{"agent.max_tool_calls": 1})
    try:
        result = copilot.ask(TURN_8)
        assert result.kind == "agent" and len(result.tool_calls) == 1
        assert any("limit" in n for n in result.notes)
    finally:
        copilot.close()


def test_write_waits_for_confirm_and_cancel_changes_nothing(pack_env):
    copilot = offline_copilot(9)
    try:
        copilot.ask(TURN_8, thread_id="w")
        before = queries.bookings_for(connection.read_connection(), "A0001")
        pending = copilot.ask("Book it.", thread_id="w")
        assert pending.kind == "confirm" and copilot.pending("w")["tool"] == "book_room"
        assert queries.bookings_for(connection.read_connection(), "A0001") == before
        cancelled = copilot.resume("w", confirm=False)
        assert cancelled.answer.startswith("Cancelled")
        assert queries.bookings_for(connection.read_connection(), "A0001") == before
        copilot.ask("Book it.", thread_id="w")
        done = copilot.resume("w", confirm=True)
        assert done.kind == "tool" and done.tool_calls[-1]["ok"], done.answer
        after = queries.bookings_for(connection.read_connection(), "A0001")
        assert len(after) == len(before) + 1 and after[-1]["room_id"] == "B-204"
    finally:
        copilot.close()
