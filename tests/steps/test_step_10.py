"""Step 10 checkpoint: connect through MCP. The scoreboard is identical in-process and over MCP."""

import pytest

from .conftest import demo_board

pytestmark = pytest.mark.step10


def test_scoreboard_identical_in_process_and_over_mcp(pack_env):
    over_mcp, copilot = demo_board(10)
    assert copilot.rt.transport.name == "mcp"
    in_process, _ = demo_board(10, **{"tools.transport": "inprocess"})
    assert over_mcp.passed == in_process.passed == over_mcp.expected(10)
    for a, b in zip(over_mcp.outcomes, in_process.outcomes):
        assert a.result.kind == b.result.kind
        assert [c["tool"] for c in a.result.tool_calls] == [c["tool"] for c in b.result.tool_calls]
    read_calls = [c for o in over_mcp.outcomes for c in o.result.tool_calls if not c.get("write")]
    assert read_calls and all(c.get("transport") == "mcp" for c in read_calls)
