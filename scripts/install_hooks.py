"""Write a plain git pre-commit hook that runs the secret scan and the language check.

The hook finds a working interpreter at commit time (the project venv on Windows or on Linux/WSL, then any
`python3`/`python` on PATH), so it keeps working when the venv is rebuilt on another platform.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = """#!/bin/sh
# Installed by scripts/install_hooks.py
for candidate in .venv/Scripts/python.exe .venv/bin/python python3 python; do
  if "$candidate" -c "import sys" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
if [ -z "$PY" ]; then echo "pre-commit: no working Python found"; exit 1; fi
"$PY" scripts/check_secrets.py || exit 1
"$PY" scripts/check_language.py || exit 1
"""


def main() -> int:
    hooks = ROOT / ".git" / "hooks"
    if not hooks.is_dir():
        print("no .git/hooks folder: run inside a git checkout")
        return 1
    target = hooks / "pre-commit"
    target.write_text(HOOK, encoding="utf-8", newline="\n")
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    print(f"pre-commit hook written to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
