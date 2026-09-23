"""The 14 scripted demo turns and the scoreboard (docs/implementation-plan.md §4.1).

All turns run in one thread, in order; turns 2 and 9 depend on the turn before
them. Write turns stop at the confirmation step and are then cancelled (or
confirmed with `confirm=True`), so a demo run leaves the database unchanged.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field

from .. import config
from ..schemas import TurnResult

DEMO_FILE = config.DATA_DIR / "demo_turns.jsonl"


def load_turns() -> list[dict]:
    return [json.loads(line) for line in DEMO_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _args_match(expected: dict, actual: dict) -> bool:
    for key, value in expected.items():
        got = actual.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            try:
                if abs(float(got) - float(value)) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
        elif str(got).lower() != str(value).lower():
            return False
    return True


def check(expect: dict, result: TurnResult) -> tuple[bool, str]:
    kind = expect["kind"]
    if result.kind != kind:
        return False, f"expected {kind}, got {result.kind}"
    if "cites" in expect:
        source, page = expect["cites"]
        if not any(c.source_id == source and c.page == page for c in result.citations):
            return False, f"no citation [{source} p.{page}]"
    if "rewrite_contains" in expect:
        rewritten = (result.query or {}).get("rewritten") or ""
        if expect["rewrite_contains"].lower() not in rewritten.lower():
            return False, "the follow-up was not rewritten before retrieval"
    if "text" in expect and result.answer.strip() != expect["text"]:
        return False, "reply text differs from the fixed template"
    if "contains" in expect and expect["contains"].lower() not in result.answer.lower():
        return False, f"answer lacks '{expect['contains']}'"
    if kind in ("tool", "agent"):
        used = [c for c in result.tool_calls if c.get("ok")]
        names = [c["tool"] for c in used]
        for tool in expect.get("tools", [expect.get("tool")] if expect.get("tool") else []):
            if tool not in names:
                return False, f"tool {tool} was not called successfully (called: {names or 'none'})"
        if "args" in expect:
            call = next((c for c in used if c["tool"] == expect["tool"]), {})
            if not _args_match(expect["args"], call.get("args", {})):
                return False, f"arguments {call.get('args')} do not match {expect['args']}"
    if kind == "confirm":
        pending = result.pending_write or {}
        if pending.get("tool") != expect["tool"]:
            return False, f"pending write is {pending.get('tool')}, not {expect['tool']}"
        if "args" in expect and not _args_match(expect["args"], pending.get("args", {})):
            return False, f"pending arguments {pending.get('args')} do not match {expect['args']}"
    return True, "ok"


@dataclass
class TurnOutcome:
    turn: int
    message: str
    first_step: int
    passed: bool
    reason: str
    result: TurnResult
    variants: list[tuple[str, bool, str]] = field(default_factory=list)
    after_confirm: TurnResult | None = None


@dataclass
class Scoreboard:
    outcomes: list[TurnOutcome]
    step: int | None
    thread_id: str

    @property
    def passed(self) -> list[int]:
        return [o.turn for o in self.outcomes if o.passed]

    def expected(self, step: int) -> list[int]:
        return [o.turn for o in self.outcomes if o.first_step <= step]

    def render(self) -> str:
        head = f"Demo scoreboard{f' at step {self.step}' if self.step else ''}: {len(self.passed)}/{len(self.outcomes)} turns pass"
        lines = [head, ""]
        for o in self.outcomes:
            mark = "PASS" if o.passed else "fail"
            lines.append(f"  {o.turn:>2}. [{mark}] {o.message[:58]:<58} -> {o.result.kind:<10} "
                         f"(first passes at step {o.first_step}){'' if o.passed else '  ' + o.reason}")
            for text, ok, why in o.variants:
                lines.append(f"      variant [{'PASS' if ok else 'fail'}] {text[:50]}{'' if ok else '  ' + why}")
        return "\n".join(lines)


def run_demo(copilot, confirm: bool = False, echo=None) -> Scoreboard:
    thread = f"demo-{uuid.uuid4().hex[:8]}"
    outcomes = []
    for turn in load_turns():
        image = turn.get("image")
        image_path = str(config.REPO_ROOT / image) if image and (config.REPO_ROOT / image).is_file() else None
        result = copilot.ask(turn["message"], thread_id=thread, image_path=image_path)
        passed, reason = check(turn["expect"], result)
        outcome = TurnOutcome(turn["turn"], turn["message"], turn["first_step"], passed, reason, result)
        if result.kind == "confirm":
            outcome.after_confirm = copilot.resume(result.thread_id, confirm)
        for variant in turn.get("variants", []):
            v_result = copilot.ask(variant, thread_id=thread)
            ok, why = check(turn["expect"], v_result)
            outcome.variants.append((variant, ok, why))
            if not ok:
                outcome.passed, outcome.reason = False, f"variant failed: {why}"
        outcomes.append(outcome)
        if echo:
            echo(f"  turn {turn['turn']:>2}: {'PASS' if outcome.passed else 'fail'} ({result.kind})")
    return Scoreboard(outcomes, copilot.settings.profile.step, thread)


def demo_settings(profile: str | None = None, overrides: dict | None = None):
    """Settings for a demo run: the campus clock pinned to `demo.today` unless COPILOT_TODAY is set."""
    base = config.load_profile(profile)
    pinned = {"app.today": base.get("demo.today")} if not os.environ.get("COPILOT_TODAY") else {}
    return config.get_settings(profile, {**pinned, **(overrides or {})})
