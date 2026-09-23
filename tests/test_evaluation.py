"""Observability and evaluation: redaction, trace report, cost rules, the evaluation set, runner, metrics, judges."""

from __future__ import annotations

import json
from collections import Counter

from campus_copilot import config
from campus_copilot.evaluation import judges, metrics
from campus_copilot.evaluation.runner import load_cases, run_eval
from campus_copilot.observability import report as trace_report
from campus_copilot.observability.cost import cost, usage_by_provider
from campus_copilot.observability.trace import Tracer, redact, redact_text, trace_files

FAKE_NV = "nvapi-" + "Ab3" * 10
FAKE_HF = "hf_" + "x1Y2" * 6
FAKE_GEMINI = "AQ." + "Zz9_" * 8


# ---------------------------------------------------------------- redaction

def test_redaction_masks_keys_and_foreign_account_ids():
    text = f"key {FAKE_NV} and {FAKE_HF} and {FAKE_GEMINI}; Authorization: Bearer abcdefghijklmnop; A0007 asked"
    masked = redact_text(text)
    for secret in (FAKE_NV, FAKE_HF, FAKE_GEMINI, "abcdefghijklmnop", "A0007"):
        assert secret not in masked
    row = redact({"account_id": "A0001", "args": {"note": "loans of A0007"}, "model": FAKE_NV})
    assert row["account_id"] == "A0001" and "A0007" not in row["args"]["note"] and FAKE_NV not in row["model"]


def test_spans_are_written_redacted(runs_dir):
    tracer = Tracer()
    with tracer.span("turn", message=f"use {FAKE_NV}", account_id="A0001"):
        with tracer.span("child", tool="get_loans"):
            pass
    lines = trace_files()[0].read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert {r["span"] for r in rows} == {"turn", "child"}
    assert FAKE_NV not in lines[-1] + lines[0] and rows[0]["parent"] == rows[1]["span_id"]


# ------------------------------------------------------------------- costs

def test_unknown_prices_stay_unknown():
    spans = [{"span": "guard_and_route", "decider": "jev", "tokens_in": 2000, "tokens_out": 600, "decider_calls": 1},
             {"span": "rag_answer", "model": "google:gemma-4-31b-it", "tokens_in": 900, "tokens_out": 80, "llm_calls": 1}]
    usage = usage_by_provider(spans)
    known, unknown, per = cost(usage, config.load_profile("baseline").get("prices"))
    assert per["google"] == "unknown" and unknown == 1
    assert abs(known - 2000 / 1e6 * 0.042) < 1e-12


def test_trace_report_after_a_demo(pack_env):
    from steps.conftest import demo_board

    demo_board(9)
    turns = trace_report.load_spans()
    rep = trace_report.build_report(turns, config.load_profile("baseline").get("prices"))
    assert rep["turns"] >= 14 and "guard_and_route" in rep["nodes"]
    assert rep["nodes"]["guard_and_route"]["p95_ms"] >= rep["nodes"]["guard_and_route"]["p50_ms"]
    assert rep["cost_at_10x"]["cohort_usd"] == round(rep["cost_at_1x"]["cohort_usd"] * 10, 4)
    assert "Slowest turns" in trace_report.render(rep)


# --------------------------------------------------------------- eval set

def test_evaluation_set_matches_the_plan():
    cases = load_cases()
    assert len(cases) >= 66 and len({c["id"] for c in cases}) == len(cases)
    by_category = Counter(c["category"] for c in cases)
    assert by_category["follow_up"] >= 6 and by_category["unanswerable"] >= 5 and by_category["multi_step"] >= 6
    assert by_category["ambiguous"] >= 5 and by_category["write"] >= 4 and by_category["adversarial"] >= 6
    assert by_category["handbook"] >= 10
    assert sum(1 for c in cases if c["language"] != "en") >= 10
    assert sum("seed-routing" in c["tags"] for c in cases) == 12
    assert all(c.get("owasp") for c in cases if c["category"] == "adversarial")
    pdf_cases = [c for c in cases if c["category"] == "handbook" and c["pages"]]
    assert len(pdf_cases) >= 6
    assert all(c["must_confirm"] for c in cases if c["category"] == "write")


def test_metrics_check_case():
    case = {"expected_route": "currency", "expected_tools": ["convert_currency"],
            "expected_args": {"amount": 20, "direction": "usd_to_khr"}, "must_clarify": False, "key_facts": ["KHR"]}
    result = {"kind": "tool", "route": "currency", "answer": "20 USD = 80,978 KHR",
              "tool_calls": [{"tool": "convert_currency", "ok": True, "args": {"amount": 20.0, "direction": "usd_to_khr"}}]}
    checks = metrics.check_case(case, result)
    assert metrics.passed(checks) and checks["citation"] is None
    result["kind"] = "clarify"
    assert not metrics.passed(metrics.check_case(case, result))


def test_offline_eval_is_fast_and_broken_down_by_language(pack_env):
    run = run_eval(config.get_settings("offline"), echo=None)
    assert run.summary["wall_seconds"] < 120
    assert run.path.is_file() and len(run.path.read_text(encoding="utf-8").splitlines()) == len(run.rows)
    text = run.report()
    for language in ("| en |", "| km |", "| km-latn |", "| mixed |"):
        assert language in text
    assert "By category:" in text and run.summary["passed"] >= 50
    assert all(not r.get("pending_write") or r["kind"] == "confirm" for r in run.rows)


def test_routing_subset_and_judges(pack_env):
    run = run_eval(config.get_settings("offline"), subset="routing", echo=None, judges=True)
    assert len(run.rows) == 12
    answered = [r for r in run.rows if r.get("kind") == "answer"]
    assert answered and all(r.get("judge_llm") is not None for r in answered)
    assert isinstance(judges.disagreement_report(run.rows), str)
    assert (config.runs_dir() / "eval" / "manual_scoring.csv").is_file()
