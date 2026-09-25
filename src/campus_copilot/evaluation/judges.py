"""Three faithfulness judges for E11 (docs/implementation-plan.md §8.11).

(a) Human: `eval/manual_scoring.csv` style export with 1-5 columns.
(b) LLM-as-judge: the chat model with a fixed rubric prompt.
(c) Decision-model citation check: `claim_support` per answer sentence against the
    retrieved passages, mapped to 1-5 by the share of supported sentences.

A disagreement report lists the cases where the judges differ by two points or more.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .. import config
from ..textutil import sentences

MANUAL_COLUMNS = ["id", "category", "language", "message", "answer", "key_facts", "faithfulness_1_5",
                  "correctness_1_5", "notes"]


def export_manual(rows: list[dict], path: Path | None = None) -> Path:
    path = path or config.runs_dir() / "eval" / "manual_scoring.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cases = {c["id"]: c for c in _cases()}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(MANUAL_COLUMNS)
        for row in rows:
            if row.get("kind") == "answer":
                writer.writerow([row["id"], row["category"], row["language"], row["message"], row["answer"],
                                 "; ".join(cases.get(row["id"], {}).get("key_facts", [])), "", "", ""])
    return path


def _cases() -> list[dict]:
    from .runner import load_cases

    return load_cases()


def laya_score(decider, answer: str, passages: list[str]) -> float | None:
    claims = [s for s in sentences(re.sub(r"\[[^\]]+\]", "", answer)) if len(s.split()) > 3]
    if not claims or not passages:
        return None
    verdicts = decider.check_claims([(c, "\n".join(passages)) for c in claims])
    share = sum(v["label"] == "supports" for v in verdicts) / len(verdicts)
    return round(1 + 4 * share, 2)


def run_judges(settings, rows: list[dict]) -> dict:
    from ..decisions.base import get_decider
    from ..llm.client import get_llm

    llm = get_llm(settings, "chat")
    decider = get_decider(settings)
    for row in rows:
        if row.get("kind") != "answer":
            continue
        verdict, reply = llm.judge_faithfulness(row["answer"], row.get("sources") or [])
        row["judge_llm"] = verdict.get("score")
        row["judge_llm_stub"] = reply.stub
        row["judge_laya"] = laya_score(decider, row["answer"], row.get("sources") or [])
        row["judge_laya_stub"] = decider.stub
    manual = config.REPO_ROOT / "eval" / "manual_scoring.csv"
    human = {}
    if manual.is_file():
        with manual.open(encoding="utf-8", newline="") as handle:
            for record in csv.DictReader(handle):
                if record.get("faithfulness_1_5"):
                    human[record["id"]] = float(record["faithfulness_1_5"])
    for row in rows:
        if row["id"] in human:
            row["judge_human"] = human[row["id"]]
    export_manual(rows)
    return {"disagreements": disagreements(rows)}


def disagreements(rows: list[dict], gap: float = 2.0) -> list[dict]:
    out = []
    for row in rows:
        scores = {k: row.get(k) for k in ("judge_human", "judge_llm", "judge_laya") if row.get(k) is not None}
        if len(scores) >= 2 and max(scores.values()) - min(scores.values()) >= gap:
            out.append({"id": row["id"], **scores, "answer": row.get("answer", "")[:160]})
    return out


def disagreement_report(rows: list[dict]) -> str:
    items = disagreements(rows)
    if not items:
        return "No case where the judges differ by two points or more."
    lines = ["| case | human | LLM | Laya | answer |", "|---|---:|---:|---:|---|"]
    for item in items:
        lines.append(f"| {item['id']} | {item.get('judge_human', '-')} | {item.get('judge_llm', '-')} | "
                     f"{item.get('judge_laya', '-')} | {item['answer']} |")
    return "\n".join(lines)
