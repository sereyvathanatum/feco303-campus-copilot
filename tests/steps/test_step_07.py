"""Step 7 checkpoint: decide with a System One model."""

import pytest

from campus_copilot.llm import prompts

from .conftest import demo_board, spans

pytestmark = pytest.mark.step07


def test_routes_clarifies_refuses_hands_off(pack_env):
    board, copilot = demo_board(7)
    assert board.passed == board.expected(7) == [1, 2, 3, 6, 10, 11, 14]
    by_turn = {o.turn: o.result for o in board.outcomes}
    assert by_turn[6].answer == prompts.CLARIFY_CONVERSION
    assert by_turn[10].answer == prompts.REFUSE_OTHER_ACCOUNT
    assert by_turn[11].answer == prompts.REFUSE_INJECTION
    assert "Fees Office" in by_turn[14].answer
    assert all(o.result.decision and o.result.decision["stub"] for o in board.outcomes)


def test_gated_rewrite_makes_fewer_calls_than_step_six(pack_env):
    board6, copilot6 = demo_board(6)
    board7, copilot7 = demo_board(7)
    ran6 = sum(1 for s in spans(copilot6, board6, "condense_query") if s.get("ran"))
    ran7 = sum(1 for s in spans(copilot7, board7, "condense_query") if s.get("ran"))
    assert ran7 < ran6 and ran7 >= 1
