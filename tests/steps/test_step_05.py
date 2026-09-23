"""Step 5 checkpoint: retrieve and answer, the first chatbot."""

import pytest

from campus_copilot.schemas import ABSTAIN_TEXT

from .conftest import demo_board

pytestmark = pytest.mark.step05


def test_first_chatbot_scoreboard_and_citations(pack_env):
    board, _ = demo_board(5)
    assert board.passed == board.expected(5) == [1, 3]
    first = board.outcomes[0].result
    assert first.kind == "answer" and any(c.page == 4 for c in first.citations) and "[campus-handbook p.4]" in first.answer
    assert board.outcomes[2].result.answer == ABSTAIN_TEXT
    timetable = board.outcomes[3].result  # no tools yet: a lookup question cannot be answered
    assert timetable.kind in {"abstain", "answer"} and not timetable.tool_calls
