"""Question builders that emit the System One wire format Laya reads (docs/implementation-plan.md §8.3)."""

from __future__ import annotations


def noul(instructions: str) -> dict:
    return {"type": "noul", "instructions": instructions}


def choice(instructions: str, criteria: dict[str, str | None]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions: str, levels: list[str]) -> dict:
    return {"type": "score", "instructions": instructions, "criteria": levels}
