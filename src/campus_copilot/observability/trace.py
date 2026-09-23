"""Trace spans written as JSONL to `runs/traces/<date>.jsonl` (docs/implementation-plan.md §8.10).

`Tracer.span(name, **attrs)` is a context manager; each span records `trace_id`,
`span`, `parent`, `start`, `ms`, `model` or `tool`, token counts, decision answers,
and any error. A redaction filter masks API keys and account IDs outside the
`account_id` field before anything is written.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config

SECRET_PATTERNS = [
    re.compile(r"nvapi-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"hf_[A-Za-z0-9]{16,}"),
    re.compile(r"AQ\.[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)(typesafe_api_key\s*[=:]\s*)[^\s\"',]+"),
]
ACCOUNT_ID = re.compile(r"\bA\d{4}\b")


def redact_text(text: str) -> str:
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", text)
    return ACCOUNT_ID.sub("A****", text)


def redact(value: Any, key: str = "") -> Any:
    if key == "account_id":
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


@dataclass
class Span:
    trace_id: str
    span: str
    parent: str | None
    start: str
    attrs: dict = field(default_factory=dict)
    ms: float = 0.0
    error: str | None = None
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def set(self, **attrs: Any) -> None:
        self.attrs.update({k: v for k, v in attrs.items() if v is not None})

    def record_llm(self, reply) -> None:
        if reply is None:
            return
        self.attrs["model"] = f"{reply.provider}:{reply.model}"
        self.attrs["tokens_in"] = self.attrs.get("tokens_in", 0) + reply.tokens_in
        self.attrs["tokens_out"] = self.attrs.get("tokens_out", 0) + reply.tokens_out
        self.attrs.setdefault("llm_calls", 0)
        self.attrs["llm_calls"] += 1
        if reply.thought_chars:
            self.attrs["thought_chars"] = self.attrs.get("thought_chars", 0) + reply.thought_chars
        if reply.stub:
            self.attrs["stub"] = True
        if reply.notes:
            self.attrs.setdefault("notes", []).extend(reply.notes)

    def as_dict(self) -> dict:
        row = {"trace_id": self.trace_id, "span": self.span, "span_id": self.span_id, "parent": self.parent,
               "start": self.start, "ms": round(self.ms, 1), **self.attrs}
        if self.error:
            row["error"] = self.error
        return redact(row)


class Tracer:
    """One tracer per turn; spans are kept in memory for the UI and appended to the JSONL file."""

    _lock = threading.Lock()

    def __init__(self, trace_id: str | None = None, write: bool = True) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex[:12]
        self.spans: list[Span] = []
        self._stack: list[str] = []
        self.write = write

    @contextmanager
    def span(self, name: str, **attrs: Any):
        item = Span(self.trace_id, name, self._stack[-1] if self._stack else None,
                    dt.datetime.now().isoformat(timespec="milliseconds"), {k: v for k, v in attrs.items() if v is not None})
        self._stack.append(item.span_id)
        started = time.perf_counter()
        try:
            yield item
        except Exception as exc:
            item.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            item.ms = (time.perf_counter() - started) * 1000
            self._stack.pop()
            self.spans.append(item)
            if self.write:
                self._append(item)

    def _append(self, item: Span) -> None:
        folder = config.runs_dir() / "traces"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{dt.date.today().isoformat()}.jsonl"
        line = json.dumps(item.as_dict(), ensure_ascii=False, default=str)
        with self._lock, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def timeline(self) -> list[dict]:
        return [s.as_dict() for s in sorted(self.spans, key=lambda s: s.start)]

    @property
    def total_ms(self) -> float:
        roots = [s for s in self.spans if s.parent is None]
        return round(sum(s.ms for s in roots), 1)


def trace_files() -> list[Path]:
    folder = config.runs_dir() / "traces"
    return sorted(folder.glob("*.jsonl")) if folder.is_dir() else []
