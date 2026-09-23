"""Graph state (docs/implementation-plan.md §8.8). Everything here is persisted by the checkpointer."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class CopilotState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]   # full thread; the model sees a trimmed window
    account_id: str                                        # from the session, never from a model
    message: str                                           # the latest message, as typed
    image_path: str | None
    image_text: str | None
    image_reading: dict | None
    decision: dict | None                                  # decider answers for this turn
    route: str | None
    action: str | None                                     # refuse | handoff | clarify | small | rag | tool | agent
    query: dict                                            # {"original": ..., "rewritten": ...}
    tool_calls: list[dict]
    pending_write: dict | None
    sources: list[dict]
    answer: str
    result: dict | None                                    # TurnResult for this turn
    flags: list[str]
    notes: list[str]
    trace_id: str
    turn: int
    slots: dict[str, Any]                                  # memory slots across turns (for example the last room search)
