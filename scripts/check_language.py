"""Neutral-language check (docs/implementation-plan.md §3.3).

Scans every tracked or new text file and prints `file:line: word` for each banned
word. Exit code 1 when any hit is found. Khmer-script text never matches the
Latin word lists and is reviewed by hand.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
RULES = tomllib.loads((ROOT / "scripts" / "language_rules.toml").read_text(encoding="utf-8"))
TEXT_SUFFIXES = {".md", ".py", ".toml", ".txt", ".yml", ".yaml", ".json", ".jsonl", ".csv",
                 ".sql", ".cfg", ".ini", ".example", ".html", ".css", ".js", ".sh", ".ps1"}
TEXT_NAMES = {"Makefile", ".gitignore", "LICENSE"}
OFF, ON = "<!-- language-check: off -->", "<!-- language-check: on -->"

AUDIENCE = re.compile(r"\b(" + "|".join(RULES["audience"]["words"]) + r")\b", re.IGNORECASE)
# Apostrophes and hyphens count as word characters, so "I've" and "e-mail" stay whole.
PRONOUNS = re.compile(r"(?<![\w'’-])(" + "|".join(RULES["pronouns"]["words"]) + r")(?![\w'’-])")
# "I" as a Roman numeral, not the pronoun: heading numbering ("I. Programs", "I) Scope") or a
# numbered term ("Term I", "Part I"). A sentence ending in the pronoun ("than I.") also passes.
NUMERAL_BEFORE = re.compile(r"\b(Term|Part|Phase|Chapter|Level|Stage|Grade|Volume|Book|Unit)\s+$")


def _numeral_i(line: str, match: re.Match) -> bool:
    if match.group(0) != "I":
        return False
    return line[match.end():match.end() + 1] in {".", ")"} or bool(NUMERAL_BEFORE.search(line[:match.start()]))


def candidate_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        files = [ROOT / line for line in out if line]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", ".venv", "runs", "__pycache__", "node_modules"}
        files = [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.relative_to(ROOT).parts)]
    return [p for p in files if p.is_file() and (p.suffix in TEXT_SUFFIXES or p.name in TEXT_NAMES)]


def _rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _is_exempt(rel: str) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in RULES["exempt"]["paths"])


def _strip_chat_fields(obj):
    fields = set(RULES["exempt"]["chat_input_fields"])
    if isinstance(obj, dict):
        return {k: (None if k in fields else _strip_chat_fields(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_chat_fields(v) for v in obj]
    return obj


def _lines_for(path: Path, rel: str) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    chat_file = any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in RULES["exempt"]["chat_input_files"])
    if chat_file and path.suffix == ".jsonl":
        lines = []
        for line in text.splitlines():
            try:
                lines.append(json.dumps(_strip_chat_fields(json.loads(line)), ensure_ascii=False))
            except json.JSONDecodeError:
                lines.append(line)
        return lines
    if chat_file and path.suffix == ".json":
        try:
            return json.dumps(_strip_chat_fields(json.loads(text)), ensure_ascii=False, indent=1).splitlines()
        except json.JSONDecodeError:
            return text.splitlines()
    return text.splitlines()


def scan_text(lines: list[str]) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    enabled = True
    for number, line in enumerate(lines, start=1):
        if OFF in line:
            enabled = False
            continue
        if ON in line:
            enabled = True
            continue
        if not enabled:
            continue
        hits.extend((number, m.group(0)) for m in AUDIENCE.finditer(line))
        hits.extend((number, m.group(0)) for m in PRONOUNS.finditer(line) if not _numeral_i(line, m))
    return hits


def scan(files: list[Path] | None = None) -> list[tuple[str, int, str]]:
    results: list[tuple[str, int, str]] = []
    for path in files if files is not None else candidate_files():
        rel = _rel(path)
        if _is_exempt(rel):
            continue
        results.extend((rel, number, word) for number, word in scan_text(_lines_for(path, rel)))
    return results


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    files = [Path(a).resolve() for a in argv] if argv else None
    hits = scan(files)
    for rel, number, word in hits:
        print(f"{rel}:{number}: {word}")
    if hits:
        print(f"language check failed: {len(hits)} hit(s)")
        return 1
    print("language check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
