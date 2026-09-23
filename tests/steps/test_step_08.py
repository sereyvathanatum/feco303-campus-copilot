"""Step 8 checkpoint: call tools over SQLite and public APIs."""

import pytest

from .conftest import demo_board, offline_copilot

pytestmark = pytest.mark.step08


def test_tools_scoreboard_scope_and_attribution(pack_env):
    board, _ = demo_board(8)
    assert board.passed == board.expected(8) == [1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 14]
    for outcome in board.outcomes:
        for call in outcome.result.tool_calls:
            assert "account_id" not in call.get("args", {})
            if call.get("kind") == "api" and call.get("ok"):
                assert call["attribution"] and call["attribution"].split(" (")[0] in outcome.result.answer


def test_errors_come_back_as_data(pack_env):
    copilot = offline_copilot(8, **{"apis.live": False})
    try:
        copilot.rt.http.fixtures_dir = pack_env / "no-fixtures"  # every API lookup now fails
        result = copilot.ask("bro change 20 dolla to luy khmer")
        assert result.kind == "tool" and result.tool_calls and result.tool_calls[0]["ok"] is False
        assert "failed" in result.answer.lower()
    finally:
        copilot.close()
