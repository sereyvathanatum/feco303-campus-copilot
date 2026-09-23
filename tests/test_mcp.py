"""MCP parity: the same tool contract in-process and over MCP (stdio subprocess servers, fixtures only)."""

from __future__ import annotations

import pytest

from campus_copilot import config
from campus_copilot.graph.nodes import InProcessTransport, Runtime
from campus_copilot.mcp.client import MCPTransport

CALLS = [
    ("get_timetable", {"course": "FECO303"}, "A0001"),
    ("get_timetable", {"course": "FECS999"}, "A0001"),
    ("get_loans", {}, "A0007"),
    ("check_book", {"isbn": "9780262046305"}, "A0001"),
    ("find_free_rooms", {"date": "tomorrow", "start": "2 pm", "end": "4 pm", "needs_projector": True}, "A0001"),
    ("find_free_rooms", {"date": "tomorrow"}, "A0001"),
    ("get_calendar", {"from": "2026-10-01", "to": "2026-10-31"}, "A0001"),
    ("search_handbook", {"query": "late assignments penalty"}, "A0001"),
    ("convert_currency", {"amount": 20, "direction": "usd_to_khr"}, "A0001"),
    ("campus_weather", {"date": "tomorrow"}, "A0001"),
    ("concept_summary", {"topic": "attention"}, "A0001"),
    ("search_books", {"query": "deep learning"}, "A0001"),
]
VOLATILE = {"ms", "transport", "fetched_at"}


@pytest.fixture(scope="module")
def transports(pack_kb, tmp_path_factory):
    import os
    import shutil

    runs = tmp_path_factory.mktemp("mcp") / "runs"
    shutil.copytree(pack_kb, runs)
    previous = os.environ.get("COPILOT_RUNS_DIR")
    os.environ["COPILOT_RUNS_DIR"] = str(runs)
    rt = Runtime(config.get_settings("offline"))
    mcp = MCPTransport(rt)
    yield InProcessTransport(rt), mcp
    mcp.close()
    if previous is None:
        os.environ.pop("COPILOT_RUNS_DIR", None)
    else:
        os.environ["COPILOT_RUNS_DIR"] = previous


def _stable(result: dict) -> dict:
    return {k: v for k, v in result.items() if k not in VOLATILE}


@pytest.mark.parametrize("name,args,account", CALLS)
def test_tool_results_are_identical_on_both_transports(transports, name, args, account):
    local, remote = transports
    a, b = local.call(name, args, account), remote.call(name, args, account)
    assert b["transport"] == "mcp"
    assert _stable(a) == _stable(b)


def test_write_tools_are_not_exposed_over_mcp(transports):
    _, remote = transports
    assert not {"book_room", "place_hold", "add_event", "run_sql"} & set(remote.tools)
    assert remote.call("book_room", {"room_id": "B-204"}, "A0001")["ok"] is False


def test_identity_comes_from_request_metadata(transports):
    _, remote = transports
    own = remote.call("get_loans", {}, "A0001")
    other = remote.call("get_loans", {}, "A0007")
    assert own["data"] != other["data"]
    assert remote.call("get_loans", {"account_id": "A0007"}, "A0001")["ok"] is False


def test_mcp_schemas_match_the_registry(transports):
    from campus_copilot.tools.registry import registry

    _, remote = transports
    for name, tool in remote.tools.items():
        assert tool["inputSchema"] == registry().get(name).mcp_schema()["inputSchema"]


def test_documents_are_resources(transports):
    _, remote = transports
    uris = [r["uri"] for r in remote.list_resources()]
    assert "campus://documents/campus-handbook" in uris
    assert "[p.4]" in remote.read_resource("campus://documents/campus-handbook")
