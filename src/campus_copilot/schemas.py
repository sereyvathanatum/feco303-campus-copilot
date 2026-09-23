"""Pydantic schemas shared across the copilot."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ABSTAIN_TEXT = "The provided sources do not cover this question."


class Citation(BaseModel):
    source_id: str
    page: int | None = None
    section: str | None = None

    def render(self) -> str:
        return f"[{self.source_id} p.{self.page}]" if self.page else f"[{self.source_id} § {self.section}]"


class GroundedAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False

    def render(self) -> str:
        if self.abstained:
            return ABSTAIN_TEXT
        marks = " ".join(dict.fromkeys(c.render() for c in self.citations if c.render() not in self.answer))
        return f"{self.answer} {marks}".strip()


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class ExtractedEvent(BaseModel):
    title: str | None = None
    date: str | None = None          # YYYY-MM-DD
    start: str | None = None         # HH:MM
    end: str | None = None
    location: str | None = None


TurnKind = Literal["answer", "abstain", "clarify", "refuse", "handoff", "tool", "agent", "confirm",
                   "small_talk", "status", "error"]


class TurnResult(BaseModel):
    """What one turn produced; the demo scoreboard, evaluation, UI, and CLI all read this."""

    kind: TurnKind
    answer: str
    route: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    pending_write: dict | None = None
    query: dict = Field(default_factory=dict)          # {"original": ..., "rewritten": ...}
    decision: dict | None = None
    flags: list[str] = Field(default_factory=list)
    trace_id: str | None = None
    thread_id: str | None = None
    notes: list[str] = Field(default_factory=list)
