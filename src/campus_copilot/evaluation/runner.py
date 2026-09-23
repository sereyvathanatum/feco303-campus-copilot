"""`cli eval --profile X`: every case in `eval/cases.jsonl` through the graph (docs/implementation-plan.md §8.11).

Each case gets a fresh thread; its `history` user turns run first. Confirmations
are auto-answered "cancel", so an evaluation never changes the campus database.
Output: `runs/eval/<profile>-<timestamp>.jsonl` plus a summary per category and
per language.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..observability.cost import cost, usage_by_provider
from . import metrics

CASES = config.REPO_ROOT / "eval" / "cases.jsonl"


def load_cases(subset: str | None = None) -> list[dict]:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not subset:
        return cases
    wanted = set(subset.split(","))
    return [c for c in cases if c["category"] in wanted or wanted & set(c.get("tags", [])) or c["id"] in wanted
            or (subset == "routing" and "seed-routing" in c.get("tags", []))]


@dataclass
class EvalRun:
    profile: str
    rows: list[dict]
    path: Path
    summary: dict

    def report(self) -> str:
        s = self.summary
        lines = [f"Evaluation: profile {self.profile}; {s['scored']} cases scored, {s['skipped']} skipped; "
                 f"{s['passed']} passed", f"Output: {self.path}", "",
                 "Checks (passed/applicable): " + ", ".join(f"{k} {v}" for k, v in s["checks"].items()),
                 f"Latency p50 {s['latency_p50_ms']} ms, p95 {s['latency_p95_ms']} ms; tokens per case "
                 f"{s['tokens_per_case']}; known cost {s['cost_usd_known']} USD; "
                 f"{s['cost_unknown_calls']} call(s) at unknown prices", "",
                 "By category:", metrics.table(self.rows, "category"), "", "By language:",
                 metrics.table(self.rows, "language")]
        skipped = [r for r in self.rows if r.get("skipped")]
        if skipped:
            lines += ["", "Skipped: " + "; ".join(f"{r['id']} ({r['skipped']})" for r in skipped)]
        failing = [r for r in self.rows if not r.get("skipped") and not r["passed"]]
        if failing:
            lines += ["", "Failing cases:"]
            for r in failing:
                bad = [k for k, v in r["checks"].items() if v is False]
                lines.append(f"  {r['id']:<11} {r['kind']:<9} failed {', '.join(bad)}: {r['message'][:60]}")
        return "\n".join(lines)


def _skip_reason(case: dict, copilot) -> str | None:
    if "needs-vision" in case.get("tags", []):
        image = config.REPO_ROOT / case.get("image", "")
        if not copilot.caps.vision:
            return "vision capability off"
        if not image.is_file():
            return "image not generated (scripts/make_images.py)"
    if "needs-adversarial-kb" in case.get("tags", []):
        row = copilot.rt.kb_conn.execute("SELECT 1 FROM documents WHERE source_id LIKE 'adversarial-%' AND "
                                         "status = 'ingested' LIMIT 1").fetchone()
        if not row:
            return "adversarial document not ingested (ingest with data.include_adversarial = true)"
    return None


def run_eval(settings, subset: str | None = None, echo=print, judges: bool = False, copilot_factory=None) -> EvalRun:
    from ..graph.build import Copilot

    factory = copilot_factory or (lambda s: Copilot(s))
    base_overrides = {"app.today": settings.profile.get("demo.today")} if not os.environ.get("COPILOT_TODAY") \
        and not settings.profile.get("app.today") else {}
    copilots: dict[str, object] = {}

    def copilot_for(overrides: dict):
        key = json.dumps(overrides, sort_keys=True)
        if key not in copilots:
            profile = config.Profile(settings.profile.name, json.loads(json.dumps(settings.profile.data)))
            for k, v in {**base_overrides, **overrides}.items():
                profile.set(k, v)
            copilots[key] = factory(config.get_settings(profile))
        return copilots[key]

    rows = []
    started_run = time.perf_counter()
    for case in load_cases(subset):
        overrides = dict(case.get("profile_overrides") or {})
        if case.get("max_tool_calls"):
            overrides["agent.max_tool_calls"] = case["max_tool_calls"]
        copilot = copilot_for(overrides)
        row = {"id": case["id"], "category": case["category"], "language": case["language"], "tags": case.get("tags"),
               "message": case["message"]}
        reason = _skip_reason(case, copilot)
        if reason:
            rows.append({**row, "skipped": reason, "kind": "-", "passed": False, "checks": {}, "latency_ms": 0,
                         "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "cost_unknown_calls": 0})
            continue
        thread = f"eval-{case['id']}-{uuid.uuid4().hex[:6]}"
        account = case.get("account_id", "A0001")
        for turn in case.get("history", []):
            prior = copilot.ask(turn["text"], thread_id=thread, account_id=account)
            if prior.kind == "confirm":
                copilot.resume(thread, False)
        image = str(config.REPO_ROOT / case["image"]) if case.get("image") else None
        t0 = time.perf_counter()
        result = copilot.ask(case["message"], thread_id=thread, account_id=account, image_path=image)
        latency = (time.perf_counter() - t0) * 1000
        spans = copilot.trace(result.trace_id)
        if result.kind == "confirm":
            copilot.resume(result.thread_id, False)
        data = result.model_dump()
        checks = metrics.check_case(case, data)
        usage = usage_by_provider(spans)
        known, unknown, per_provider = cost(usage, settings.profile.get("prices", {}) or {})
        row.update({"kind": result.kind, "route": result.route, "answer": result.answer,
                    "citations": [c.render() for c in result.citations],
                    "tools": [c["tool"] for c in result.tool_calls], "pending_write": result.pending_write,
                    "query": result.query, "checks": checks, "passed": metrics.passed(checks),
                    "fact_recall": metrics.fact_recall(case, result.answer), "latency_ms": round(latency, 1),
                    "tokens_in": sum(u["tokens_in"] for u in usage.values()),
                    "tokens_out": sum(u["tokens_out"] for u in usage.values()), "usage": usage,
                    "cost_usd": known, "cost_unknown_calls": unknown, "cost_by_provider": per_provider,
                    "decider": (result.decision or {}).get("decider"), "stub": bool((result.decision or {}).get("stub")),
                    "sources": [s["text"] for s in result.sources[:4]], "trace_id": result.trace_id})
        rows.append(row)
        if echo:
            echo(f"  {case['id']:<11} {'PASS' if row['passed'] else 'fail'} {result.kind:<9} {latency:7.0f} ms")
    for copilot in copilots.values():
        copilot.close()
    if judges:
        from .judges import run_judges

        run_judges(settings, rows)
    out = config.runs_dir() / "eval"
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out / f"{settings.profile.name.replace('/', '_')}-{stamp}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    summary = metrics.summarize(rows)
    summary["wall_seconds"] = round(time.perf_counter() - started_run, 1)
    (out / f"{path.stem}.summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return EvalRun(settings.profile.name, rows, path, summary)
