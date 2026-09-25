"""Token counts and cost per provider, from trace spans and the `[prices]` table of the profile.

A price marked "unknown" stays unknown: calls to that provider are counted, never
estimated silently.
"""

from __future__ import annotations

from collections import defaultdict

PRICE_KEYS = {"laya": "laya", "nim": "nim_chat", "google": "google_chat", "stub": None}


def provider_of(span: dict) -> str | None:
    if span.get("decider") and span.get("span") in {"guard_and_route", "judge_passages", "verify_answer", "risk_gate"}:
        return "stub" if span.get("stub") or span.get("decider") == "stub" else span["decider"].split(":")[0]
    model = span.get("model")
    if model and ":" in str(model):
        return str(model).split(":")[0]
    return None


def usage_by_provider(spans: list[dict]) -> dict[str, dict]:
    usage: dict[str, dict] = defaultdict(lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0})
    for span in spans:
        provider = provider_of(span)
        if provider is None or not (span.get("tokens_in") or span.get("llm_calls") or span.get("decider_calls")):
            continue
        entry = usage[provider]
        entry["calls"] += int(span.get("llm_calls") or span.get("decider_calls") or 1)
        entry["tokens_in"] += int(span.get("tokens_in") or 0)
        entry["tokens_out"] += int(span.get("tokens_out") or 0)
    return dict(usage)


def cost(usage: dict[str, dict], prices: dict) -> tuple[float, int, dict]:
    """(known cost in USD, number of calls with an unknown price, cost per provider)."""
    known, unknown, per = 0.0, 0, {}
    for provider, entry in usage.items():
        key = PRICE_KEYS.get(provider, provider)
        if key is None:
            per[provider] = 0.0
            continue
        table = prices.get(key) or {}
        price_in, price_out = table.get("input", "unknown"), table.get("output", "unknown")
        if not isinstance(price_in, (int, float)) or not isinstance(price_out, (int, float)):
            unknown += entry["calls"]
            per[provider] = "unknown"
            continue
        value = entry["tokens_in"] / 1e6 * price_in + entry["tokens_out"] / 1e6 * price_out
        per[provider] = round(value, 8)
        known += value
    return round(known, 8), unknown, per
