"""Release verification (maintenance): fresh venv -> install -> checks -> offline tests -> demo -> eval -> live.

    python scripts/verify.py            # offline stages
    python scripts/verify.py --live     # also the live suite (needs keys in .env and network)
    python scripts/verify.py --reuse    # use the current interpreter instead of a fresh venv

Prints a pass/fail table and exits non-zero when any stage fails.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(label: str, cmd: list[str], env: dict, results: list, timeout: int = 1800) -> bool:
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
        ok = proc.returncode == 0
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-1:] or [""]
    except subprocess.TimeoutExpired:
        ok, tail = False, [f"timeout after {timeout} s"]
    results.append((label, ok, round(time.perf_counter() - started, 1), tail[0][:110]))
    print(f"{'PASS' if ok else 'FAIL'}  {label}  ({results[-1][2]} s)  {tail[0][:110]}", flush=True)
    return ok


def main() -> int:
    live, reuse = "--live" in sys.argv, "--reuse" in sys.argv
    results: list = []
    work = Path(tempfile.mkdtemp(prefix="verify-"))
    env = {**os.environ, "COPILOT_RUNS_DIR": str(work / "runs"), "PYTHONIOENCODING": "utf-8"}
    offline_env = {**env, "COPILOT_PROFILE": "offline"}
    if reuse:
        python = sys.executable
    else:
        venv = work / "venv"
        if not run("create fresh virtual environment", [sys.executable, "-m", "venv", str(venv)], env, results):
            return report(results)
        python = str(venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
        run("upgrade pip", [python, "-m", "pip", "install", "-q", "--upgrade", "pip"], env, results)
        if not run("install requirements.txt", [python, "-m", "pip", "install", "-q", "-r", "requirements.txt"], env,
                   results, timeout=3600):
            return report(results)
    cli = [python, "-m", "campus_copilot.cli"]
    run("language check", [python, "scripts/check_language.py"], env, results)
    run("secret scan", [python, "scripts/check_secrets.py"], env, results)
    run("offline tests", [python, "-m", "pytest", "-q", "-p", "no:cacheprovider"], env, results)
    run("cli check (offline)", cli + ["check", "--no-network"], offline_env, results)
    run("cli seed", cli + ["seed"], offline_env, results)
    run("cli ingest (offline)", cli + ["ingest"], offline_env, results)
    run("cli demo (offline, 14 turns)", cli + ["demo"], offline_env, results)
    for step in (5, 9, 12):
        run(f"cli step {step} scoreboard", cli + ["step", str(step)], offline_env, results)
    run("cli eval (offline)", cli + ["eval"], offline_env, results)
    run("cli eval --vision (offline)", cli + ["eval", "--vision"], offline_env, results)
    if live:
        live_env = {**env, "COPILOT_LIVE_TESTS": "1"}
        live_env.pop("COPILOT_PROFILE", None)
        run("cli check (live)", cli + ["check"], live_env, results)
        run("cli laya-smoke", cli + ["laya-smoke"], live_env, results)
        run("live test suite", [python, "-m", "pytest", "-q", "-m", "live", "-p", "no:cacheprovider"], live_env, results)
    return report(results)


def report(results: list) -> int:
    print("\n| Stage | Result | Seconds | Last line |\n|---|---|---:|---|")
    for label, ok, seconds, tail in results:
        print(f"| {label} | {'PASS' if ok else 'FAIL'} | {seconds} | {tail.replace('|', '/')} |")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} stages passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
