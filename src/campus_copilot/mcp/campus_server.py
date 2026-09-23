"""MCP server for campus read tools and the knowledge-base documents as resources.

Write tools (`book_room`, `place_hold`, `add_event`) are deliberately not exposed
over MCP, which keeps the trust boundary visible: writes stay inside the app,
behind its risk gate and confirmation step.

Run: `python -m campus_copilot.mcp.campus_server` (stdio) or `python -m campus_copilot.cli mcp-serve campus`.
"""

from __future__ import annotations

from .common import build_server, serve

CAMPUS_TOOLS = ["search_handbook", "get_timetable", "get_deadlines", "find_free_rooms", "check_book", "get_loans",
                "get_calendar"]


def server():
    return build_server("campus-copilot-campus", CAMPUS_TOOLS, with_resources=True)


if __name__ == "__main__":
    serve(server())
