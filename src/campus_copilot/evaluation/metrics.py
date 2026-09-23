"""Evaluation metrics (docs/implementation-plan.md §8.11).

Per case: route, tool-selection, and argument accuracy; clarify, abstain, confirm,
and block correctness; citation coverage; key-fact recall; rewrite checks;
forbidden strings; loop limits. Results are always broken down per category and
per language, never averaged away.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

CHECKS = ["route", "tools", "args", "clarify", "abstain", "confirm", "block", "citation", "facts", "rewrite",
          "forbidden", "loop"]


def _args_match(expected: dict, actual: dict) -> bool:
    for key, value in expected.items():
        got = actual.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            if str(got).lower() != str(value).lower():
                return False
        else:
            try:
                if abs(float(got) - float(value)) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
    return True


def check_case(case: dict, result: dict) -> dict:
    """Every applicable check as True/False; checks that do not apply are None."""
    kind = result.get("kind")
    answer = (result.get("answer") or "").lower()
    calls = [c for c in result.get("tool_calls") or [] if c.get("ok")]
    pending = result.get("pending_write") or {}
    names = [c["tool"] for c in calls] + ([pending["tool"]] if pending.get("tool") else [])
    out: dict[str, bool | None] = {k: None for k in CHECKS}
    if case.get("expected_route") is not None:
        out["route"] = result.get("route") == case["expected_route"]
    expected_tools = case.get("expected_tools") or []
    if expected_tools:
        out["tools"] = all(t in names for t in expected_tools)
    if case.get("expected_args"):
        target = expected_tools[0] if expected_tools else None
        candidates = [pending.get("args", {})] if pending.get("tool") == target else []
        candidates += [c.get("args", {}) for c in calls if c["tool"] == target]
        out["args"] = any(_args_match(case["expected_args"], a) for a in candidates)
    out["clarify"] = (kind == "clarify") == bool(case.get("must_clarify"))
    out["abstain"] = (kind == "abstain") == bool(case.get("must_abstain"))
    out["confirm"] = (kind == "confirm") == bool(case.get("must_confirm"))
    out["block"] = (kind == "refuse") == bool(case.get("must_block"))
    if case.get("source_ids") and not case.get("must_abstain") and case.get("expected_route") == "handbook":
        pages = case.get("pages") or []
        out["citation"] = any(c["source_id"] in case["source_ids"] and (not pages or c.get("page") in pages)
                              for c in result.get("citations") or [])
    facts = case.get("key_facts") or []
    if facts:
        out["facts"] = sum(f.lower() in answer for f in facts) / len(facts) >= 0.5
    rewritten = ((result.get("query") or {}).get("rewritten") or "").lower()
    if case.get("expected_rewrite_contains"):
        out["rewrite"] = all(w.lower() in rewritten for w in case["expected_rewrite_contains"])
    if case.get("rewrite_must_not_contain"):
        out["rewrite"] = not any(w.lower() in rewritten for w in case["rewrite_must_not_contain"])
    if case.get("forbidden"):
        out["forbidden"] = not any(f.lower() in answer for f in case["forbidden"])
    if case.get("max_tool_calls"):
        out["loop"] = len(result.get("tool_calls") or []) <= int(case["max_tool_calls"])
    return out


def passed(checks: dict) -> bool:
    return all(v for v in checks.values() if v is not None)


def fact_recall(case: dict, answer: str) -> float | None:
    facts = case.get("key_facts") or []
    if not facts:
        return None
    return sum(f.lower() in (answer or "").lower() for f in facts) / len(facts)


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[index], 1)


def _rate(values: list) -> str:
    applicable = [v for v in values if v is not None]
    if not applicable:
        return "-"
    return f"{sum(applicable)}/{len(applicable)}"


def group(rows: list[dict], key: str) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    return dict(sorted(groups.items()))


def summarize(rows: list[dict]) -> dict:
    scored = [r for r in rows if not r.get("skipped")]
    return {
        "cases": len(rows), "scored": len(scored), "skipped": len(rows) - len(scored),
        "passed": sum(r["passed"] for r in scored),
        "checks": {c: _rate([r["checks"].get(c) for r in scored]) for c in CHECKS},
        "latency_p50_ms": percentile([r["latency_ms"] for r in scored], 0.5),
        "latency_p95_ms": percentile([r["latency_ms"] for r in scored], 0.95),
        "tokens_per_case": round(statistics.fmean([r["tokens_in"] + r["tokens_out"] for r in scored]), 1) if scored else 0,
        "cost_usd_known": round(sum(r["cost_usd"] for r in scored), 6),
        "cost_unknown_calls": sum(r["cost_unknown_calls"] for r in scored),
    }


def table(rows: list[dict], key: str) -> str:
    lines = [f"| {key} | n | passed | route | tools | args | clarify | abstain | confirm | block | citation | facts | "
             "p50 ms | p95 ms |", "|---|---:|---:|---|---|---|---|---|---|---|---|---|---:|---:|"]
    for name, items in group([r for r in rows if not r.get("skipped")], key).items():
        rates = [_rate([r["checks"].get(c) for r in items]) for c in
                 ("route", "tools", "args", "clarify", "abstain", "confirm", "block", "citation", "facts")]
        lines.append(f"| {name} | {len(items)} | {sum(r['passed'] for r in items)} | " + " | ".join(rates) +
                     f" | {percentile([r['latency_ms'] for r in items], 0.5)} | "
                     f"{percentile([r['latency_ms'] for r in items], 0.95)} |")
    return "\n".join(lines)
