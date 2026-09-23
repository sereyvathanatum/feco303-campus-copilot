"""Write a plain git pre-commit hook that runs the secret scan and the language check."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = """#!/bin/sh
# Installed by scripts/install_hooks.py
PY="{python}"
"$PY" scripts/check_secrets.py || exit 1
"$PY" scripts/check_language.py || exit 1
"""


def main() -> int:
    hooks = ROOT / ".git" / "hooks"
    if not hooks.is_dir():
        print("no .git/hooks folder: run inside a git checkout")
        return 1
    target = hooks / "pre-commit"
    target.write_text(HOOK.format(python=Path(sys.executable).as_posix()), encoding="utf-8", newline="\n")
    target.chmod(target.stat().st_mode | stat.S_IEXEC)
    print(f"pre-commit hook written to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
