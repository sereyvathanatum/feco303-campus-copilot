"""Secret scan (docs/implementation-plan.md §7.1, rule 6).

Rejects any tracked or new file containing a string shaped like a real key:
`nvapi-` followed by 20 or more characters, or a non-placeholder
`LAYA_API_KEY=` value (the optional laya-serve bearer key). Exit code 1 when a candidate secret is found.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NVAPI = re.compile(r"nvapi-[A-Za-z0-9_\-]{20,}")
LAYA_KEY = re.compile(r"LAYA_API_KEY\s*=\s*['\"]?([A-Za-z0-9_\-]{8,})")
PLACEHOLDERS = {"laya-replace-with-a-real-key"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ttf", ".otf", ".db", ".sqlite", ".ico",
                 ".woff", ".woff2"}


def candidate_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        return [ROOT / line for line in out if line and (ROOT / line).is_file()]
    except (OSError, subprocess.CalledProcessError):
        skip = {".git", ".venv", "runs", "__pycache__"}
        return [p for p in ROOT.rglob("*") if p.is_file() and not skip & set(p.relative_to(ROOT).parts)]


def _is_reference(value: str) -> bool:
    """Values that name a key instead of holding one: variables, lookups, empty strings."""
    return (value in PLACEHOLDERS or value.startswith(("$", "os.", "{", "<", "env", "...")) or value in {"", "None"})


def scan_text(text: str) -> list[tuple[int, str]]:
    hits = []
    for number, line in enumerate(text.splitlines(), start=1):
        if NVAPI.search(line) and "nvapi-replace-with-a-real-key" not in line:
            hits.append((number, "nvapi key shape"))
        for match in LAYA_KEY.finditer(line):
            if not _is_reference(match.group(1)):
                hits.append((number, "LAYA_API_KEY value"))
    return hits


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    files = [Path(a).resolve() for a in argv] if argv else candidate_files()
    found = 0
    for path in files:
        if path.suffix.lower() in SKIP_SUFFIXES or path.name == ".env":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, kind in scan_text(text):
            found += 1
            try:
                rel = path.relative_to(ROOT).as_posix()
            except ValueError:
                rel = path.as_posix()
            print(f"{rel}:{number}: possible secret ({kind})")
    if found:
        print(f"secret scan failed: {found} hit(s)")
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
