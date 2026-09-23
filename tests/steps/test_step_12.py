"""Step 12 checkpoint: images and the architecture decision."""

import pytest

from campus_copilot import config

from .conftest import demo_board

pytestmark = pytest.mark.step12


def test_full_scoreboard_and_adr_template(pack_env):
    board, _ = demo_board(12)
    assert board.passed == board.expected(12) and len(board.passed) == 14
    poster = board.outcomes[12]
    assert poster.result.kind == "confirm" and poster.after_confirm.answer.startswith("Cancelled")
    adr = (config.REPO_ROOT / "docs" / "adr_template.md").read_text(encoding="utf-8")
    for heading in ("## Context", "## Options", "## Decision", "## Consequences"):
        assert heading in adr
