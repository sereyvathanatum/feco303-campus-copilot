"""`cli trace-report`: latency and cost from the JSONL traces (docs/implementation-plan.md §8.10).

Reports p50/p95 latency per node, calls per turn by provider, tokens per turn, cost
per turn and at 10x usage from the profile's price table, and the slowest turns.
A price marked unknown stays unknown and is never estimated silently.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

from .cost import cost, usage_by_provider
from .trace import trace_files

TURNS_PER_SEAT = 200
SEATS = 40


def load_spans(paths: list[Path] | None = None, last: int | None = None) -> dict[str, list[dict]]:
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for path in paths or trace_files():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                span = json.loads(line)
                by_trace[span["trace_id"]].append(span)
    turns = {tid: spans for tid, spans in by_trace.items() if any(s["span"] == "turn" for s in spans)}
    if last:
        ordered = sorted(turns, key=lambda tid: min(s["start"] for s in turns[tid]))
        turns = {tid: turns[tid] for tid in ordered[-last:]}
    return turns


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))], 1)


def build_report(turns: dict[str, list[dict]], prices: dict) -> dict:
    per_node: dict[str, list[float]] = defaultdict(list)
    turn_rows = []
    unknown_total = 0
    for trace_id, spans in turns.items():
        for span in spans:
            per_node[span["span"]].append(float(span.get("ms", 0)))
        root = next(s for s in spans if s["span"] == "turn")
        usage = usage_by_provider(spans)
        known, unknown, per_provider = cost(usage, prices)
        unknown_total += unknown
        turn_rows.append({"trace_id": trace_id, "ms": root["ms"], "message": root.get("message", "")[:70],
                          "calls": {p: u["calls"] for p, u in usage.items()},
                          "tokens": sum(u["tokens_in"] + u["tokens_out"] for u in usage.values()),
                          "cost": known, "unknown_calls": unknown})
    n = len(turn_rows) or 1
    calls: dict[str, float] = defaultdict(float)
    for row in turn_rows:
        for provider, count in row["calls"].items():
            calls[provider] += count / n
    mean_cost = sum(r["cost"] for r in turn_rows) / n
    return {
        "turns": len(turn_rows),
        "nodes": {name: {"n": len(v), "p50_ms": _pct(v, 0.5), "p95_ms": _pct(v, 0.95)}
                  for name, v in sorted(per_node.items(), key=lambda kv: -statistics.fmean(kv[1]))},
        "calls_per_turn": {p: round(c, 2) for p, c in sorted(calls.items())},
        "tokens_per_turn": round(sum(r["tokens"] for r in turn_rows) / n, 1),
        "cost_per_turn_usd": round(mean_cost, 8),
        "cost_at_1x": {"assumptions": f"{TURNS_PER_SEAT} turns per seat, {SEATS} seats",
                       "per_seat_usd": round(mean_cost * TURNS_PER_SEAT, 6),
                       "cohort_usd": round(mean_cost * TURNS_PER_SEAT * SEATS, 4)},
        "cost_at_10x": {"per_seat_usd": round(mean_cost * TURNS_PER_SEAT * 10, 6),
                        "cohort_usd": round(mean_cost * TURNS_PER_SEAT * SEATS * 10, 4)},
        "unknown_price_calls": unknown_total,
        "slowest": sorted(turn_rows, key=lambda r: -r["ms"])[:5],
    }


def render(report: dict) -> str:
    lines = [f"Trace report over {report['turns']} turn(s)", "", "| node | n | p50 ms | p95 ms |", "|---|---:|---:|---:|"]
    lines += [f"| {name} | {v['n']} | {v['p50_ms']} | {v['p95_ms']} |" for name, v in report["nodes"].items()]
    lines += ["", "Calls per turn by provider: " + (", ".join(f"{p} {c}" for p, c in report["calls_per_turn"].items())
                                                  or "none"),
              f"Tokens per turn: {report['tokens_per_turn']}",
              f"Known cost per turn: {report['cost_per_turn_usd']} USD",
              f"Cost at 1x ({report['cost_at_1x']['assumptions']}): {report['cost_at_1x']['per_seat_usd']} USD per seat, "
              f"{report['cost_at_1x']['cohort_usd']} USD per cohort",
              f"Cost at 10x: {report['cost_at_10x']['per_seat_usd']} USD per seat, {report['cost_at_10x']['cohort_usd']} "
              "USD per cohort"]
    if report["unknown_price_calls"]:
        lines.append(f"{report['unknown_price_calls']} model call(s) have an unknown price and are not included; "
                     "set them in [prices] of the profile to include them.")
    lines += ["", "Slowest turns:"]
    lines += [f"  {r['ms']:>8.0f} ms  {r['message']}" for r in report["slowest"]]
    return "\n".join(lines)
