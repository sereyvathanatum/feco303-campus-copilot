"""The tool registry (docs/implementation-plan.md §8.6).

One spec per tool: name, description, Pydantic argument model, read/write flag,
and source. The native tool schema, the JSON-protocol description, and the MCP
tool are all generated from that spec, so the three stay identical.

Rules enforced here:
* selection is not execution: only registered tools run, after argument validation;
* identity never comes from a model: `account_id` is taken from the context and no
  argument model exposes it;
* errors are data: every failure returns `{"ok": false, "error": ...}`.
"""

from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from .. import config


@dataclass
class ToolContext:
    settings: Any
    account_id: str
    today: dt.date
    now: dt.datetime
    http: Any = None
    kb_conn: Any = None
    embedder: Any = None
    decider: Any = None
    db_path: Any = None

    @classmethod
    def create(cls, settings, account_id: str, http=None, db_path=None) -> "ToolContext":
        from .http import HttpClient

        today = config.today(settings.profile)  # pinned in demos and tests, otherwise the real date
        now = dt.datetime.combine(today, dt.datetime.now().time().replace(microsecond=0))
        return cls(settings, account_id, today, now, http or HttpClient(settings), db_path=db_path)


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[[ToolContext, BaseModel], dict]
    write: bool = False
    kind: str = "db"            # db | api | rag
    source: str = ""

    def parameters(self) -> dict:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        return schema

    def native_schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": self.parameters()}}

    def json_protocol(self) -> dict:
        return {"name": self.name, "description": self.description, "args": self.parameters()}

    def mcp_schema(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.parameters()}


@dataclass
class Registry:
    tools: dict[str, ToolSpec] = field(default_factory=dict)

    def register(self, spec: ToolSpec) -> None:
        if "account_id" in spec.args_model.model_fields:
            raise ValueError(f"{spec.name}: account_id must come from the session, never from tool arguments")
        self.tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self.tools.get(name)

    def names(self, include_write: bool = True, include_sql: bool = False) -> list[str]:
        return [n for n, s in self.tools.items()
                if (include_write or not s.write) and (include_sql or n != "run_sql")]

    def specs(self, include_write: bool = True, include_sql: bool = False) -> list[ToolSpec]:
        return [self.tools[n] for n in self.names(include_write, include_sql)]

    def run(self, name: str, args: dict | None, ctx: ToolContext, allow_write: bool = False) -> dict:
        started = time.perf_counter()
        args = dict(args or {})
        spec = self.tools.get(name)
        if spec is None:
            return error(name, args, f"unknown tool '{name}'; registered tools: {', '.join(self.tools)}", started)
        if spec.write and not allow_write:
            return error(name, args, "write tools run only after confirmation", started)
        if "account_id" in args:
            return error(name, args, "account_id is taken from the session and cannot be passed as an argument",
                         started)
        try:
            parsed = spec.args_model.model_validate(args)
        except ValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'args'}: {e['msg']}" for e in exc.errors())
            return error(name, args, f"invalid arguments: {problems}", started)
        try:
            result = spec.func(ctx, parsed)
        except Exception as exc:  # tool errors are data, never exceptions in the graph
            return error(name, args, f"{type(exc).__name__}: {exc}", started)
        result.setdefault("ok", True)
        result.update({"tool": name, "args": parsed.model_dump(exclude_none=True), "write": spec.write,
                       "kind": spec.kind, "ms": round((time.perf_counter() - started) * 1000, 1)})
        return result


def error(tool: str, args: dict, message: str, started: float | None = None) -> dict:
    return {"ok": False, "tool": tool, "args": args, "error": message, "summary": f"{tool} failed: {message}",
            "ms": round((time.perf_counter() - started) * 1000, 1) if started else 0.0}


_REGISTRY: Registry | None = None


def registry() -> Registry:
    global _REGISTRY
    if _REGISTRY is None:
        from . import campus, public_apis, text_to_sql

        reg = Registry()
        for spec in campus.SPECS + public_apis.SPECS + text_to_sql.SPECS:
            reg.register(spec)
        _REGISTRY = reg
    return _REGISTRY
